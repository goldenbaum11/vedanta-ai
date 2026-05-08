"""Embedding pipeline.

Phase 1: a placeholder that defers to ChromaDB's default embedding function
(`all-MiniLM-L6-v2`). Phase 2 will swap in a multilingual model better
suited to Sanskrit / Devanagari content (candidates: `intfloat/multilingual-e5-large`,
`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`).
"""

from __future__ import annotations

from typing import Sequence


def embed_batch(texts: Sequence[str]) -> list[list[float]]:
    """Embed a batch of texts.

    Phase 1 stub. Real implementation will be wired in alongside the corpus
    ingestion script in Phase 2.
    """
    raise NotImplementedError(
        "Custom embeddings not implemented yet. "
        "Phase 1 uses ChromaDB's default embedding function via `vector_store.add_documents`."
    )
