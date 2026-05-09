"""Corpus ingestion driver.

Walks a directory and dispatches each file to the appropriate chunker
in `backend/knowledge/chunker.py`, then batches the resulting verse /
paragraph chunks into the named ChromaDB collection.

Format auto-detection:
- `.jsonl`              → `chunk_jsonl_verses` (preferred for sacred texts)
- `.md`, `.markdown`    → `chunk_structured_text`
- `.txt`                → `chunk_paragraphs`
- `.pdf`                → `chunk_pdf` (requires `pypdf`)

Caller may force a single format via `format_override`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from . import chunker
from ..rag import vector_store

logger = logging.getLogger(__name__)

Format = Literal["jsonl", "structured_text", "paragraphs", "pdf"]

_EXT_TO_FORMAT: dict[str, Format] = {
    ".jsonl": "jsonl",
    ".md": "structured_text",
    ".markdown": "structured_text",
    ".txt": "paragraphs",
    ".pdf": "pdf",
}

ChunkIter = Iterator[tuple[str, str, dict[str, Any]]]
ChunkerFn = Callable[[Path], ChunkIter]

_FORMAT_DISPATCH: dict[Format, ChunkerFn] = {
    "jsonl": chunker.chunk_jsonl_verses,
    "structured_text": chunker.chunk_structured_text,
    "paragraphs": chunker.chunk_paragraphs,
    "pdf": chunker.chunk_pdf,
}


def _detect_format(path: Path) -> Format | None:
    return _EXT_TO_FORMAT.get(path.suffix.lower())


def _iter_supported_files(directory: Path) -> list[Path]:
    return sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and _detect_format(p) is not None
    )


def ingest_directory(
    *,
    collection_name: str,
    directory: Path,
    format_override: Format | None = None,
    reset: bool = False,
    batch_size: int = 64,
) -> int:
    """Ingest every supported file under `directory`. Returns total chunk count.

    `reset=True` deletes the collection before ingesting (use when changing
    embedding providers, since vector dims won't match).
    """
    if not directory.exists():
        raise FileNotFoundError(f"Corpus directory does not exist: {directory}")

    if reset:
        logger.info("Resetting collection: %s", collection_name)
        vector_store.reset_collection(collection_name)

    files = _iter_supported_files(directory)
    if not files:
        logger.warning("No supported files found under %s", directory)
        return 0

    total = 0
    pending_ids: list[str] = []
    pending_docs: list[str] = []
    pending_metas: list[dict[str, Any]] = []

    def flush() -> int:
        nonlocal pending_ids, pending_docs, pending_metas
        if not pending_docs:
            return 0
        added = vector_store.add_documents(
            collection_name=collection_name,
            documents=pending_docs,
            metadatas=pending_metas,
            ids=pending_ids,
        )
        pending_ids, pending_docs, pending_metas = [], [], []
        return added

    for path in files:
        fmt = format_override or _detect_format(path)
        if fmt is None:
            logger.warning("Skipping unsupported file: %s", path)
            continue
        chunker_fn = _FORMAT_DISPATCH[fmt]
        try:
            chunks = list(chunker_fn(path))
        except Exception as exc:  # noqa: BLE001 - per-file failures should not kill the run
            logger.error("Failed to chunk %s (%s): %s", path, fmt, exc)
            continue
        if not chunks:
            logger.info("No chunks produced from %s", path)
            continue
        for chunk_id, doc, meta in chunks:
            pending_ids.append(chunk_id)
            pending_docs.append(doc)
            pending_metas.append(meta)
            if len(pending_docs) >= batch_size:
                total += flush()
        logger.info("Queued %d chunks from %s", len(chunks), path)

    total += flush()
    logger.info("Ingested %d total chunks into '%s'.", total, collection_name)
    return total
