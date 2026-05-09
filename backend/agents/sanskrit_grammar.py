"""Module 1b — Sanskrit Grammar agent.

Phase 2: same `vedic_texts` corpus as Vedic Scholar, but the agent
focuses on grammatical analysis (sandhi / samasa / vibhakti / dhatu /
pratyaya / chandas) of the retrieved verse.

Phase 3+ will integrate SanskritNLP / Sanskrit Heritage Platform for
deterministic structural parsing alongside this LLM-driven analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from ..rag import retriever
from ..schemas import AgentResponse
from ._base import respond_with_llm

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
"""


def _augment(query: str, context_block: str) -> str:
    if not context_block:
        return query
    return (
        "Reference passages from the local corpus (use these for parsing):\n\n"
        f"{context_block}\n\n"
        "---\n"
        f"User question: {query}\n\n"
        "Provide a word-by-word grammatical breakdown of the relevant verse. "
        "Cite by bracketed number and verse reference."
    )


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    try:
        _, citations, context_block = await retriever.retrieve_with_context(
            collection_name=COLLECTION, query=query, top_k=TOP_K
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG retrieval failed for sanskrit_grammar: %s", exc)
        citations, context_block = [], ""

    augmented = _augment(query, context_block)
    return await respond_with_llm(
        agent="sanskrit_grammar",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra={
            "phase": 2,
            "rag_enabled": True,
            "corpus": COLLECTION,
            "hits": len(citations),
            "structural_parser": "pending",
        },
    )
