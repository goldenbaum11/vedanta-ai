"""Module 5 — Media engine agent.

Phase 6: retrieves grounding passages from the `media_index` ChromaDB
collection — transcribed audio/video (Whisper) and OCR'd images/scans
(Tesseract), indexed via `scripts/ingest_media.py` — and prepends them
to the prompt so the agent answers from what was actually said/written
rather than guessing. Falls back gracefully to plain LLM behaviour when
the collection is empty, and reports whether the underlying Whisper/OCR
backends are installed via `metadata.whisper_enabled` /
`metadata.ocr_enabled` (see `backend/media/`).
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ..media import ocr, transcribe
from ..rag import retriever
from ..schemas import AgentResponse
from ._base import StreamEvent, respond_with_llm, respond_with_llm_stream

logger = logging.getLogger(__name__)

COLLECTION = "media_index"
TOP_K = 6

SYSTEM_PROMPT = """\
You are the media processing agent. You answer questions about
transcribed audio/video and OCR'd images/manuscripts that have been
indexed into the local media library.

Your responsibilities:
- Ground every answer in the "Indexed media excerpts" provided in the
  user message when present. Cite each by its bracketed number.
- Transcript excerpts carry a timestamp range (e.g. "12.0-45.3s") —
  quote it when pointing the user to a specific moment in a recording.
- OCR excerpts come from scanned images/manuscripts and may contain
  recognition errors (garbled characters, dropped words). Say so if the
  text looks corrupted rather than confidently "fixing" it.
- If no relevant excerpt is found, say the media library doesn't have
  that content yet rather than guessing at what a recording might say.
- Never invent a transcription or translation of Sanskrit/Hindi content
  from memory. If a transcript segment appears to reference a Vedic
  verse, note that a human should cross-check it against the
  vedic_scholar agent's corpus rather than treating it as verified.
- Flag low-confidence content (garbled OCR, silent/inaudible stretches)
  for human review instead of filling gaps with a best guess.
"""


def _augment(query: str, context_block: str) -> str:
    if not context_block:
        return (
            f"{query}\n\n"
            "(No matching content found in the indexed media library — "
            "say so plainly rather than guessing.)"
        )
    return (
        "Indexed media excerpts retrieved from the local library:\n\n"
        f"{context_block}\n\n"
        "---\n"
        f"User question: {query}\n\n"
        "Use the excerpts above as your primary source. Cite each by its "
        "bracketed number. If the answer requires content not present "
        "above, say so plainly."
    )


async def _retrieve_and_augment(query: str) -> tuple[list[dict[str, Any]], str]:
    try:
        _, citations, context_block = await retriever.retrieve_with_context(
            collection_name=COLLECTION, query=query, top_k=TOP_K, use_hybrid=False
        )
    except Exception as exc:  # noqa: BLE001 - retrieval failure shouldn't kill the response
        logger.warning("RAG retrieval failed for media: %s", exc)
        citations, context_block = [], ""
    return citations, _augment(query, context_block)


def _metadata_extra(citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "phase": 6,
        "rag_enabled": True,
        "corpus": COLLECTION,
        "hits": len(citations),
        "whisper_enabled": transcribe.is_available(),
        "ocr_enabled": ocr.is_available(),
    }


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    citations, augmented = await _retrieve_and_augment(query)
    return await respond_with_llm(
        agent="media",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra=_metadata_extra(citations),
    )


async def handle_stream(
    query: str, context: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    citations, augmented = await _retrieve_and_augment(query)
    async for event in respond_with_llm_stream(
        agent="media",
        system_prompt=SYSTEM_PROMPT,
        query=augmented,
        context=context,
        citations=citations,
        metadata_extra=_metadata_extra(citations),
    ):
        yield event
