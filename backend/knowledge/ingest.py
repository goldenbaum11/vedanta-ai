"""Corpus ingestion utilities.

Phase 1 implements only the simplest case: chunk plain-text / markdown
files line-by-paragraph and add them to a named ChromaDB collection.
Phase 2 will add PDF parsing, Sanskrit-aware verse chunking, and
metadata derivation (source / chapter / verse / language).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from ..rag import vector_store

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_SUFFIXES: tuple[str, ...] = (".txt", ".md", ".markdown")


def _iter_text_files(directory: Path) -> Iterable[Path]:
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_TEXT_SUFFIXES:
            yield path


def _chunk_paragraphs(text: str, *, min_chars: int = 80) -> list[str]:
    """Split on blank lines, drop trivial chunks."""
    chunks: list[str] = []
    for raw in text.split("\n\n"):
        candidate = raw.strip()
        if len(candidate) >= min_chars:
            chunks.append(candidate)
    return chunks


def ingest_directory(*, collection_name: str, directory: Path) -> int:
    """Ingest every supported text file under `directory`. Returns chunk count."""
    if not directory.exists():
        raise FileNotFoundError(f"Corpus directory does not exist: {directory}")

    total = 0
    for path in _iter_text_files(directory):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning("Skipping non-UTF8 file: %s", path)
            continue
        chunks = _chunk_paragraphs(text)
        if not chunks:
            continue
        ids = [f"{path.stem}:{i}" for i in range(len(chunks))]
        metadatas = [
            {"source": str(path.relative_to(directory)), "chunk_index": i}
            for i in range(len(chunks))
        ]
        added = vector_store.add_documents(
            collection_name=collection_name,
            documents=chunks,
            metadatas=metadatas,
            ids=ids,
        )
        total += added
        logger.info("Ingested %d chunks from %s", added, path)
    return total
