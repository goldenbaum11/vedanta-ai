"""Module 1b — Sanskrit Grammar agent.

Layered analysis pipeline:

1. **RAG retrieval** from the ``vedic_texts`` collection picks the
   verse(s) the user is asking about (so the user can write
   "BG 2.47 morphology" instead of pasting the verse).
2. **Deterministic parsing** via the optional Sanskrit Heritage
   Platform client (`backend.grammar`) gives a structural ground
   truth (sandhi splits, root forms, case endings) the LLM can
   reference. When the SHP integration is disabled (default) or
   unavailable (network/timeout), this step is skipped and the
   agent gracefully proceeds with LLM-only analysis.
3. **LLM grammar synthesis** uses a strong system prompt that asks
   for a word-by-word breakdown, citing both the corpus passage and
   the SHP analysis when present.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from ..grammar import ParseResult, get_default_parser
from ..rag import retriever
from ..schemas import AgentResponse
from ._base import StreamEvent, respond_with_llm, respond_with_llm_stream

logger = logging.getLogger(__name__)

COLLECTION = "vedic_texts"
TOP_K = 3

SYSTEM_PROMPT = """\
You are a Sanskrit grammar analysis agent.

Your responsibilities:
- Parse Sanskrit verses: identify sandhi (phonetic junctions), samasa (compound
  words), vibhakti (case endings), dhatu (verb roots), pratyaya (suffixes),
  and chandas (meter).
- Produce a structured grammatical breakdown of each word in a verse.
- Explain grammatical rules in accessible language for students learning Sanskrit.
- Use standard Devanagari notation and IAST transliteration side-by-side.
- Reference Panini's Ashtadhyayi rules when relevant (cite the sutra number).

When reference passages from the local corpus are provided, parse those
passages preferentially and cite each by its bracketed number. If the
user asks about a verse not present above, state that explicitly and
ask them to paste the verse text.

When a "Structural parser analysis" block is provided, treat it as
deterministic ground truth from the Sanskrit Heritage Platform and
quote sandhi splits / root identifications from it directly. If your
intuition disagrees with the parser, say so and explain why instead
of silently overriding it.
"""


def _augment(
    query: str,
    context_block: str,
    parse: ParseResult | None,
) -> str:
    parts: list[str] = []
    if context_block:
        parts.append(
            "Reference passages from the local corpus (use these for parsing):\n\n"
            f"{context_block}"
        )
    if parse and parse.success and parse.analysis:
        parts.append(
            f"Structural parser analysis (from {parse.parser}):\n\n"
            f"{parse.analysis}"
        )
    if not parts:
        return query
    parts.append("---")
    parts.append(f"User question: {query}")
    parts.append(
        "Provide a word-by-word grammatical breakdown of the relevant verse. "
        "Cite the corpus passage by its bracketed number and reference the "
        "structural parser analysis when it confirms your splits. Use "
        "Devanagari + IAST side-by-side."
    )
    return "\n\n".join(parts)


def _looks_like_sanskrit(text: str) -> bool:
    """Heuristic: skip the parser for plainly non-Sanskrit prose."""
    if not text:
        return False
    if any("\u0900" <= ch <= "\u097F" for ch in text):
        return True
    # IAST-ish: presence of common diacritics or transliterated syllables.
    iast_markers = ("ā", "ī", "ū", "ṛ", "ṝ", "ṃ", "ḥ", "ś", "ṣ", "ñ", "ṅ", "ṭ", "ḍ")
    return any(m in text for m in iast_markers)


def _extract_parser_input(
    citations: list[dict[str, Any]], query: str
) -> str | None:
    """Pick the best string to feed to the deterministic parser.

    Preference order:
    1. Sanskrit text from the top retrieved citation's full body
       (typical case: "explain BG 2.47" → SHP gets the actual verse).
    2. The user query itself, if it already contains Devanagari/IAST.
    3. None — skip the parser.
    """
    for hit in citations:
        body = (hit.get("full_text") or hit.get("snippet") or "").strip()
        if body and _looks_like_sanskrit(body):
            return body[:600]
    if _looks_like_sanskrit(query):
        return query[:600]
    return None


async def _retrieve(query: str) -> tuple[list[dict[str, Any]], str]:
    try:
        _, citations, context_block = await retriever.retrieve_with_context(
            collection_name=COLLECTION, query=query, top_k=TOP_K
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG retrieval failed for sanskrit_grammar: %s", exc)
        citations, context_block = [], ""
    return citations, context_block


@dataclass(frozen=True)
class _ParseAttempt:
    """Tracks the outcome of trying to parse Sanskrit grounding text.

    We need to distinguish three states for downstream metadata:
    * not tried (integration disabled or no Sanskrit input found),
    * tried and succeeded (use the analysis in the prompt),
    * tried and failed (don't pollute the prompt, but still record
      that the parser was attempted so monitoring can spot SHP
      outages).
    """

    parser_name: str
    attempted: bool
    result: ParseResult | None


async def _maybe_parse(
    citations: list[dict[str, Any]], query: str
) -> _ParseAttempt:
    parser = get_default_parser()
    if parser is None:
        return _ParseAttempt(parser_name="disabled", attempted=False, result=None)
    payload = _extract_parser_input(citations, query)
    if payload is None:
        return _ParseAttempt(parser_name=parser.name, attempted=False, result=None)
    try:
        result = await parser.analyze(payload)
    except Exception as exc:  # noqa: BLE001 - parser must never break the agent
        logger.info("SHP parser raised %s; continuing without it.", exc)
        return _ParseAttempt(parser_name=parser.name, attempted=True, result=None)
    return _ParseAttempt(
        parser_name=parser.name,
        attempted=True,
        result=result if result.success else None,
    )


def _metadata_extra(
    citations: list[dict[str, Any]], attempt: _ParseAttempt
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "phase": 3,
        "rag_enabled": True,
        "corpus": COLLECTION,
        "hits": len(citations),
        "structural_parser": attempt.parser_name,
        "structural_parser_attempted": attempt.attempted,
        "structural_parser_used": bool(attempt.result and attempt.result.success),
    }
    return extra


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    citations, context_block = await _retrieve(query)
    attempt = await _maybe_parse(citations, query)
    augmented = _augment(query, context_block, attempt.result)
    return await respond_with_llm(
        agent="sanskrit_grammar",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra=_metadata_extra(citations, attempt),
    )


async def handle_stream(
    query: str, context: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    citations, context_block = await _retrieve(query)
    attempt = await _maybe_parse(citations, query)
    augmented = _augment(query, context_block, attempt.result)
    async for event in respond_with_llm_stream(
        agent="sanskrit_grammar",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra=_metadata_extra(citations, attempt),
    ):
        yield event
