"""High-level RAG retrieval helpers used by agents.

Per project rules, RAG retrieval is called BEFORE LLM inference for any
knowledge-grounded query. Agents call `retrieve(...)` here rather than
hitting the vector store directly.
"""

from __future__ import annotations

from typing import Any

from . import vector_store


async def retrieve(
    *,
    collection_name: str,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve the top-k most relevant chunks from a collection.

    Returns a list of dicts with keys: id, document, metadata, distance.
    Async-friendly so callers can `await` even though Chroma's call is
    currently synchronous; this future-proofs us for an async backend.
    """
    return vector_store.query(
        collection_name=collection_name,
        text=query,
        n_results=top_k,
    )


def format_citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project retrieval hits into the citation shape used in `AgentResponse`."""
    citations: list[dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        citations.append(
            {
                "id": hit.get("id"),
                "source": meta.get("source"),
                "chapter": meta.get("chapter"),
                "verse": meta.get("verse"),
                "language": meta.get("language"),
                "snippet": (hit.get("document") or "")[:280],
                "distance": hit.get("distance"),
            }
        )
    return citations
