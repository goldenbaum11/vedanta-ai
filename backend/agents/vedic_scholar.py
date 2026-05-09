"""Module 1 — Vedic Scholar agent.

Phase 2: retrieves verse-level passages from the `vedic_texts` ChromaDB
collection and prepends them to the user prompt so the LLM cites the
loaded corpus rather than its training data. Falls back gracefully to a
plain LLM call when the corpus is empty (still useful for general
questions about traditions/philosophy).
"""

from __future__ import annotations

import logging
from typing import Any

from ..rag import retriever
from ..schemas import AgentResponse
from ._base import respond_with_llm

logger = logging.getLogger(__name__)

COLLECTION = "vedic_texts"
TOP_K = 8

SYSTEM_PROMPT = """\
You are a Vedic scholar agent within the Vedanta AI system.

Your responsibilities:
- Translate Sanskrit verses from the Vedas, Upanishads, Puranas, Bhagavad Gita,
  and related texts with high fidelity.
- Always cite the source: text name, chapter (adhyaya), and verse number (shloka).
- For every translation, provide three layers:
    1. Word-for-word gloss (anvaya)
    2. Literal translation
    3. Meaning in context (bhava)
- Provide multiple commentary perspectives when philosophically significant:
  Advaita (Shankaracharya), Vishishtadvaita (Ramanujacharya), Dvaita (Madhvacharya).
  Attribute each view clearly.
- Preferred reference scholars: Swami Gambhirananda, Swami Sivananda,
  Swami Vivekananda, Sri Aurobindo, A.C. Bhaktivedanta Swami (Vaishnava texts).
- Never invent verses, verse numbers, Sanskrit text, or commentaries. If a verse
  the user asks about is not present in the retrieved reference passages, you
  MUST say "this verse is not in the loaded corpus" and stop. Do NOT reconstruct
  Sanskrit from memory; do NOT paraphrase a different verse to fill the gap.
- Respond in the language the user writes in (English, Sanskrit, Hindi).

When reference passages from the local corpus are provided in the user
message under "Reference passages", treat them as your primary source of
truth and cite them by the bracketed number. If the user asks about a
verse not present in the reference passages, say so explicitly rather
than fabricate.
"""


def _augment(query: str, context_block: str) -> str:
    if not context_block:
        return query
    return (
        "Reference passages retrieved from the local corpus:\n\n"
        f"{context_block}\n\n"
        "---\n"
        f"User question: {query}\n\n"
        "Use the reference passages above as your primary source. "
        "Cite each by its bracketed number AND its verse reference. "
        "If the answer requires a verse not present above, say so plainly."
    )


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    try:
        _, citations, context_block = await retriever.retrieve_with_context(
            collection_name=COLLECTION, query=query, top_k=TOP_K
        )
    except Exception as exc:  # noqa: BLE001 - retrieval failure shouldn't kill the response
        logger.warning("RAG retrieval failed for vedic_scholar: %s", exc)
        citations, context_block = [], ""

    augmented = _augment(query, context_block)
    return await respond_with_llm(
        agent="vedic_scholar",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra={
            "phase": 2,
            "rag_enabled": True,
            "corpus": COLLECTION,
            "hits": len(citations),
        },
    )
