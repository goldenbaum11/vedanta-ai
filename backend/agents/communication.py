"""Module 2 — Communication agent (Phase 3).

Handles incoming messages from students and the public on behalf of
the ashram. The agent:

1. Detects **escalation triggers** (distress, harm, harassment,
   medical / legal / financial concerns, requests for personal
   guidance) before any LLM call. Escalation is conservative — when in
   doubt we prefer to flag for a human.
2. Retrieves grounding passages from the ``communications`` ChromaDB
   collection (ashram FAQ, schedule, donation policy, safeguarding
   policy, etc.) so replies stay factual and on-policy.
3. Hands the augmented prompt to the local LLM with a strong system
   prompt encoding ashram tone and refusal rules.
4. Stops generating and returns a fixed compassionate response when
   distress is detected.

The escalation flag flows through the dispatcher to the API response
and is persisted on the messages row so a future review queue can
filter on it.
"""

from __future__ import annotations

import logging
import re
from typing import Any, AsyncIterator

from ..rag import retriever
from ..schemas import AgentResponse
from ._base import StreamEvent, respond_with_llm, respond_with_llm_stream

logger = logging.getLogger(__name__)

COLLECTION = "communications"
TOP_K = 5

SYSTEM_PROMPT = """\
You are the communication agent for an ashram. You answer messages
from students, visitors, and the public on behalf of the ashram.

Your operating principles:
- You speak FOR the ashram, but you are not a teacher and you do not
  give individual spiritual direction. You are a courteous,
  well-informed first responder.
- Your answers MUST be grounded in the reference passages provided
  under "Ashram knowledge base" in the user message. If the answer is
  not there, say so plainly and offer the relevant ashram email or
  the contact page rather than guessing.
- Tone: warm, plain, unhurried, non-promotional. No theatrics, no
  hyperbole, no marketing language. If you would not say it in person
  to a respected elder visiting the gate, do not write it.
- Keep responses concise unless the question genuinely requires
  depth. For Instagram DM-style replies, aim under ~300 characters.
- NEVER promise outcomes ("this will heal you", "you will achieve
  enlightenment"), give medical / legal / financial advice, perform
  divination, or claim authority you do not have.
- NEVER quote a Sanskrit verse unless it appears verbatim in the
  reference passages.
- If the message contains signs of crisis, harm, harassment, or any
  matter requiring a human teacher, you will already have been
  instructed to stop and emit only a brief acknowledgement; honour
  that instruction.

Always classify the inbound message into ONE of:
[spiritual_question] [event_inquiry] [donation_support]
[personal_guidance] [logistical_admin] [distress_flag] [other]

Return your classification at the very end of your reply on its own
line in the form:

  [classification: <label>]

If you have cited a passage from the reference list, cite it inline
by its bracketed number (e.g. "[2]") so the reader can verify.
"""

DISTRESS_RESPONSE = (
    "Thank you for reaching out. I have flagged your message for one of "
    "the teachers, who will get back to you personally and as soon as "
    "they can.\n\n"
    "If you are in immediate distress or thinking of harming yourself, "
    "please contact a crisis service right now: in India, iCall on "
    "+91 9152987821 or Vandrevala Foundation on 1860 2662 345; "
    "elsewhere, please call your local emergency services. You are "
    "not alone, and we are glad you wrote.\n\n"
    "[classification: distress_flag]"
)


# -- Escalation detection -------------------------------------------------

_DISTRESS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsuicid",
        r"\bkill (?:myself|him|her|them)\b",
        r"\bend (?:my|his|her|their) life\b",
        r"\bself[- ]?harm",
        r"\bcutting myself\b",
        r"\bwant(?:ing)? to die\b",
        r"\bno reason to live\b",
        r"\babuse",
        r"\bharass(?:ed|ment|ing)?\b",
        r"\bassault(?:ed)?\b",
        r"\brape",
        r"\bmolest",
        r"\bin danger\b",
        r"\bbeing threatened\b",
    )
)

_PERSONAL_GUIDANCE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bshould I (leave|divorce|quit|marry)\b",
        r"\bguru\b.*\b(accept|take) me\b",
        r"\binitiat(?:e|ion) me\b",
        r"\b(diksha|deeksha)\b",
        r"\bpersonal (mantra|sadhana)\b",
    )
)

_PROFESSIONAL_REFERRAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdiagnose",
        r"\bprescrib",
        r"\bmedication\b",
        r"\b(legal|lawsuit|sue)\b",
        r"\binvestment advice\b",
        r"\btax (advice|deduction)\b",  # we still answer general donation Qs;
        # this catches "give me tax advice".
    )
)


def _classify_escalation(query: str) -> tuple[str | None, bool]:
    """Return (reason, escalate) where reason is a short label or None."""
    if any(p.search(query) for p in _DISTRESS_PATTERNS):
        return "distress", True
    if any(p.search(query) for p in _PERSONAL_GUIDANCE_PATTERNS):
        return "personal_guidance", True
    if any(p.search(query) for p in _PROFESSIONAL_REFERRAL_PATTERNS):
        return "professional_referral", True
    return None, False


# -- Retrieval helpers ----------------------------------------------------


async def _retrieve(query: str) -> tuple[list[dict[str, Any]], str]:
    try:
        _, citations, context_block = await retriever.retrieve_with_context(
            collection_name=COLLECTION,
            query=query,
            top_k=TOP_K,
            use_hybrid=False,  # FAQ has no verse refs, plain semantic suffices.
        )
    except Exception as exc:  # noqa: BLE001 - retrieval failure shouldn't kill reply
        logger.warning("RAG retrieval failed for communication: %s", exc)
        citations, context_block = [], ""
    return citations, context_block


def _augment(query: str, context_block: str, escalation_reason: str | None) -> str:
    if context_block:
        prefix = (
            "Ashram knowledge base (cite by bracketed number where used):\n\n"
            f"{context_block}\n\n"
            "---\n"
        )
    else:
        prefix = (
            "Ashram knowledge base: (no relevant passage found — "
            "say so if the question requires authoritative info, and "
            "point the reader to the contact page).\n\n"
            "---\n"
        )
    suffix = ""
    if escalation_reason == "personal_guidance":
        suffix = (
            "\n\nNOTE: This message asks for individual spiritual "
            "direction (initiation, personal mantra, life decision, "
            "etc.). Do not give such guidance yourself. Acknowledge "
            "warmly, explain that personal guidance is offered by "
            "senior teachers via guidance@example-ashram.org, and "
            "classify as [personal_guidance]."
        )
    elif escalation_reason == "professional_referral":
        suffix = (
            "\n\nNOTE: This message touches on medical / legal / "
            "financial matters. Do NOT give professional advice. "
            "Acknowledge warmly, explain that the ashram does not "
            "give such advice, and refer to a qualified professional. "
            "Classify under [other] or [logistical_admin] as fits."
        )
    return f"{prefix}User message: {query}{suffix}"


def _metadata_extra(
    citations: list[dict[str, Any]], escalation_reason: str | None
) -> dict[str, Any]:
    extra: dict[str, Any] = {
        "phase": 3,
        "rag_enabled": True,
        "corpus": COLLECTION,
        "hits": len(citations),
        "review_required": True,  # all comms-agent replies queue for review
    }
    if escalation_reason:
        extra["escalation_reason"] = escalation_reason
    return extra


# -- Public entry points --------------------------------------------------


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    reason, escalate = _classify_escalation(query)
    if reason == "distress":
        return AgentResponse(
            agent="communication",
            text=DISTRESS_RESPONSE,
            citations=[],
            metadata={
                **_metadata_extra([], reason),
                "short_circuit": True,
                "llm_invoked": False,
            },
            escalate=True,
        )
    citations, context_block = await _retrieve(query)
    augmented = _augment(query, context_block, reason)
    return await respond_with_llm(
        agent="communication",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra=_metadata_extra(citations, reason),
        escalate=escalate,
    )


async def handle_stream(
    query: str, context: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    reason, escalate = _classify_escalation(query)
    if reason == "distress":
        # Skip the LLM entirely. Emit a meta event then a single
        # done event with the canned response so the frontend's
        # normal state machine still works.
        yield {
            "type": "meta",
            "agent": "communication",
            "citations": [],
            "escalate": True,
            "metadata": {
                **_metadata_extra([], reason),
                "short_circuit": True,
                "llm_invoked": False,
            },
        }
        yield {"type": "done", "text": DISTRESS_RESPONSE}
        return

    citations, context_block = await _retrieve(query)
    augmented = _augment(query, context_block, reason)
    async for event in respond_with_llm_stream(
        agent="communication",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra=_metadata_extra(citations, reason),
        escalate=escalate,
    ):
        yield event
