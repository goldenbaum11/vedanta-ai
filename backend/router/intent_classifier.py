"""Intent classifier.

Maps an incoming user message to one of the six agent labels:
    vedic_scholar, sanskrit_grammar, communication, infosec, survival, media

Strategy:
1. Cheap keyword pre-classifier for obvious cases (works offline).
2. LLM-based fallback with a tightly constrained prompt that must return
   one of the canonical labels. If the LLM is unreachable we degrade
   gracefully to the keyword winner (or "communication" as the safe default).
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from ..models.llm_client import LLMUnavailableError, get_llm_client
from ..schemas import AGENT_NAMES, AgentName, IntentResult

logger = logging.getLogger(__name__)

KEYWORD_RULES: dict[AgentName, tuple[str, ...]] = {
    "vedic_scholar": (
        "veda", "vedic", "upanishad", "gita", "bhagavad", "shloka", "verse",
        "translation", "translate", "puran", "purana", "ramayan", "mahabharat",
        "shankar", "ramanuj", "advaita", "dvaita", "brahma sutra",
    ),
    "sanskrit_grammar": (
        "sandhi", "samasa", "vibhakti", "dhatu", "pratyaya", "panini",
        "ashtadhyayi", "grammar", "parse", "iast", "devanagari", "chandas",
    ),
    "communication": (
        "dm", "instagram", "email", "message a student", "donation", "event",
        "ashram visit", "schedule", "appointment", "register", "rsvp",
    ),
    "infosec": (
        "login", "auth", "audit", "breach", "intrusion", "anomaly",
        "permission", "access log", "rate limit", "encryption", "security",
        "firewall", "pii",
    ),
    "survival": (
        "ayurveda", "herbal", "remedy", "first aid", "compost", "permaculture",
        "rainwater", "solar", "biogas", "ferment", "preserve", "seed",
        "soil", "earthbuilding", "shelter", "off-grid", "off grid",
    ),
    "media": (
        "transcribe", "transcript", "video", "audio", "ocr", "image",
        "manuscript", "whisper", "subtitle", "caption",
    ),
}

_INTENT_SYSTEM_PROMPT = (
    "You are a strict intent classifier inside the Vedanta AI system.\n"
    "Choose EXACTLY ONE label for the user message from this set:\n"
    "  vedic_scholar, sanskrit_grammar, communication, infosec, survival, media\n\n"
    "Definitions:\n"
    "- vedic_scholar: translating, citing, or interpreting Sanskrit sacred texts.\n"
    "- sanskrit_grammar: parsing, sandhi/samasa/vibhakti analysis, Panini rules.\n"
    "- communication: handling DMs / emails / event or donation queries from students or public.\n"
    "- infosec: monitoring, auditing, access control, encryption, security alerts.\n"
    "- survival: practical living: ayurveda, food, water, energy, shelter, agriculture.\n"
    "- media: transcribing audio/video, OCR on images, indexing media files.\n\n"
    "Reply with ONLY the label, lower-case, no punctuation, no extra words."
)


def _keyword_scores(message: str) -> dict[AgentName, int]:
    text = message.lower()
    scores: dict[AgentName, int] = {name: 0 for name in AGENT_NAMES}
    for label, keywords in KEYWORD_RULES.items():
        for kw in keywords:
            if kw in text:
                scores[label] += 1
    return scores


def _devanagari_present(message: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", message))


def _best_keyword_match(scores: dict[AgentName, int]) -> tuple[AgentName | None, int]:
    best_label: AgentName | None = None
    best_score = 0
    for label, score in scores.items():
        if score > best_score:
            best_label = label
            best_score = score
    return best_label, best_score


def _normalize_label(raw: str) -> AgentName | None:
    cleaned = raw.strip().lower().split()[0] if raw.strip() else ""
    cleaned = cleaned.strip(".,:;'\"`")
    return cleaned if cleaned in AGENT_NAMES else None  # type: ignore[return-value]


async def classify(message: str) -> IntentResult:
    """Classify a message and return the chosen agent + confidence."""
    scores = _keyword_scores(message)
    keyword_label, keyword_score = _best_keyword_match(scores)

    if _devanagari_present(message):
        scores["vedic_scholar"] += 2
        if keyword_score < 2:
            keyword_label = "vedic_scholar"
            keyword_score = max(keyword_score, 2)

    if keyword_score >= 2 and keyword_label is not None:
        return IntentResult(
            agent=keyword_label,
            confidence=min(0.6 + 0.1 * keyword_score, 0.95),
            rationale="keyword match",
        )

    try:
        llm = get_llm_client()
        raw = await llm.complete(
            system_prompt=_INTENT_SYSTEM_PROMPT,
            user_message=message,
            temperature=0.0,
        )
    except LLMUnavailableError as exc:
        logger.warning("Intent LLM fallback unavailable, using keyword: %s", exc)
        return IntentResult(
            agent=keyword_label or "communication",
            confidence=0.4 if keyword_label else 0.2,
            rationale="llm_unavailable_keyword_fallback",
        )

    label = _normalize_label(raw)
    if label is None:
        logger.warning("LLM returned non-canonical intent: %r", raw)
        return IntentResult(
            agent=keyword_label or "communication",
            confidence=0.35,
            rationale=f"llm_invalid:{raw[:60]}",
        )
    return IntentResult(agent=label, confidence=0.85, rationale="llm_classifier")


def supported_agents() -> Iterable[AgentName]:
    return AGENT_NAMES
