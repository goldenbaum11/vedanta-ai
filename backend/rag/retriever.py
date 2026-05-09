"""High-level RAG retrieval helpers used by agents.

Per project rules, RAG retrieval is called BEFORE LLM inference for any
knowledge-grounded query. Agents call `retrieve(...)` here rather than
hitting the vector store directly.
"""

from __future__ import annotations

import re
from typing import Any

from . import vector_store

# "BG 2.47", "Bhagavad Gita 18.66", "chapter 2 verse 47", "2.47", "12.5–10".
_VERSE_REF = re.compile(
    r"\b(?P<chapter>\d{1,3})[.:](?P<verse>\d{1,3})\b"
)


def extract_verse_refs(query: str) -> list[tuple[str, str]]:
    """Pull (chapter, verse) tuples out of a query for metadata-filtered lookup."""
    return [(m.group("chapter"), m.group("verse")) for m in _VERSE_REF.finditer(query)]


async def retrieve(
    *,
    collection_name: str,
    query: str,
    top_k: int = 5,
    where: dict[str, Any] | None = None,
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
        where=where,
    )


def _dedupe_by_id(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for hit in hits:
        hid = hit.get("id")
        if hid in seen:
            continue
        if hid is not None:
            seen.add(hid)
        out.append(hit)
    return out


async def hybrid_retrieve(
    *,
    collection_name: str,
    query: str,
    top_k: int = 8,
    boost_per_ref: int = 4,
) -> list[dict[str, Any]]:
    """Semantic retrieval, *plus* exact metadata fetches for any verse refs
    detected in the query (e.g. "BG 2.47"). The metadata-filtered hits are
    placed first so the prompt builder always sees the explicitly-requested
    verse, regardless of where pure-semantic retrieval ranked it.
    """
    refs = extract_verse_refs(query)
    pinned: list[dict[str, Any]] = []
    if refs:
        for chapter, verse in refs:
            where = {
                "$and": [
                    {"chapter": {"$eq": chapter}},
                    {"verse": {"$eq": verse}},
                ]
            }
            ref_hits = await retrieve(
                collection_name=collection_name,
                query=query,
                top_k=boost_per_ref,
                where=where,
            )
            pinned.extend(ref_hits)

    semantic = await retrieve(
        collection_name=collection_name, query=query, top_k=top_k
    )
    combined = _dedupe_by_id(pinned + semantic)
    return combined[: top_k + (boost_per_ref * len(refs))]


def format_citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project retrieval hits into the citation shape used in `AgentResponse`.

    Each citation carries both a 280-char `snippet` (compact, for list views
    and logs) and a `full_text` field with the entire chunk document (for
    verifiable expansion in the UI). Including the full chunk text is what
    makes the citation auditable — the user can confirm exactly what the
    LLM saw, including Sanskrit and IAST that may have been truncated in
    the snippet.
    """
    citations: list[dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        document = hit.get("document") or ""
        citations.append(
            {
                "id": hit.get("id"),
                "source": meta.get("source"),
                "chapter": meta.get("chapter"),
                "verse": meta.get("verse"),
                "language": meta.get("language") or meta.get("language_tags"),
                "commentary_author": meta.get("commentary_author"),
                "tradition": meta.get("tradition"),
                "snippet": document[:280],
                "full_text": document,
                "distance": hit.get("distance"),
            }
        )
    return citations


def format_context_block(hits: list[dict[str, Any]]) -> str:
    """Render retrieved hits as a numbered reference block for an LLM prompt."""
    if not hits:
        return ""
    lines: list[str] = []
    for idx, hit in enumerate(hits, start=1):
        meta = hit.get("metadata") or {}
        header_parts: list[str] = [f"[{idx}]"]
        if meta.get("source"):
            header_parts.append(str(meta["source"]))
        if meta.get("chapter") is not None:
            header_parts.append(f"ch. {meta['chapter']}")
        if meta.get("verse") is not None:
            header_parts.append(f"v. {meta['verse']}")
        if meta.get("commentary_author"):
            header_parts.append(f"({meta['commentary_author']})")
        lines.append(" ".join(header_parts))
        body = (hit.get("document") or "").strip()
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip()


async def retrieve_with_context(
    *,
    collection_name: str,
    query: str,
    top_k: int = 5,
    use_hybrid: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Convenience: retrieve + format citations + format context block.

    When `use_hybrid=True` (default), explicit verse references in the
    query are pinned via metadata filtering before semantic retrieval.
    """
    if use_hybrid:
        hits = await hybrid_retrieve(
            collection_name=collection_name, query=query, top_k=top_k
        )
    else:
        hits = await retrieve(
            collection_name=collection_name, query=query, top_k=top_k
        )
    citations = format_citations(hits)
    context_block = format_context_block(hits)
    return hits, citations, context_block
