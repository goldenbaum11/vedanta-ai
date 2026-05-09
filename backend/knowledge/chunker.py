"""Corpus chunkers.

Each chunker yields `(chunk_id, document_text, metadata)` tuples ready
for ChromaDB. ChromaDB requires metadata values to be primitives
(str/int/float/bool/None), so list-shaped fields are flattened into
comma-separated strings.

Chunkers:
- `chunk_jsonl_verses` — preferred for sacred texts. One verse per JSON
  Lines record. Chunk = sanskrit + iast + translation + (optional)
  commentary, with full verse metadata preserved.
- `chunk_structured_text` — markdown-ish input with `## Chapter X` and
  `### Verse Y` headers (useful for PDF-extracted text after light
  hand-cleanup).
- `chunk_pdf` — flat extraction via pypdf; paragraphs become chunks.
  Lossy for verse-aligned content but useful for prose commentary.
- `chunk_paragraphs` — Phase 1 fallback for plain `.txt`/`.md`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

VerseChunk = tuple[str, str, dict[str, Any]]


def _flatten_metadata(meta: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Coerce metadata to ChromaDB-compatible primitives."""
    flat: dict[str, Any] = {"source": source}
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            flat[key] = value
        elif isinstance(value, list):
            flat[key] = ", ".join(str(v) for v in value)
        else:
            flat[key] = str(value)
    return flat


def _build_verse_document(record: dict[str, Any]) -> str:
    """Concatenate available language layers into a single retrievable string.

    A verse-locator header (e.g. "Bhagavad Gita 2.47") is prepended so
    queries like "explain BG 2.47" match the right chunk via lexical
    overlap, not just semantic similarity to the body.
    """
    parts: list[str] = []
    source = (record.get("source") or "").strip()
    chapter = record.get("chapter")
    verse = record.get("verse")
    locator = source
    if chapter is not None and verse is not None:
        locator = f"{source} {chapter}.{verse}".strip()
    elif chapter is not None:
        locator = f"{source} Chapter {chapter}".strip()
    if locator:
        author = record.get("commentary_author")
        header = f"[{locator}]"
        if author:
            header += f" — {author}"
        parts.append(header)

    if record.get("sanskrit"):
        parts.append(f"Sanskrit: {record['sanskrit']}")
    if record.get("iast"):
        parts.append(f"IAST: {record['iast']}")
    if record.get("translation"):
        parts.append(f"Translation: {record['translation']}")
    if record.get("commentary"):
        author = record.get("commentary_author") or "Commentary"
        parts.append(f"{author}: {record['commentary']}")
    return "\n".join(parts).strip()


def chunk_jsonl_verses(path: Path) -> Iterator[VerseChunk]:
    """Yield one chunk per JSON Lines record. Schema (all fields optional except source):

    {
      "source": "Bhagavad Gita",
      "chapter": "2",
      "verse": "47",
      "sanskrit": "...",
      "iast": "...",
      "translation": "...",
      "commentary": "...",
      "commentary_author": "Shankaracharya",
      "tradition": "Advaita",
      "language_tags": ["sanskrit", "iast", "english"]
    }
    """
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid JSONL on %s:%d (%s)", path, line_no, exc)
                continue
            source = record.get("source") or path.stem
            chapter = record.get("chapter")
            verse = record.get("verse")
            commentary_author = record.get("commentary_author")

            doc = _build_verse_document(record)
            if not doc:
                continue

            chunk_id_parts = [source, str(chapter or ""), str(verse or ""), commentary_author or ""]
            chunk_id = ":".join(p for p in chunk_id_parts if p) or f"{path.stem}:{line_no}"

            metadata = _flatten_metadata(
                {
                    "chapter": str(chapter) if chapter is not None else None,
                    "verse": str(verse) if verse is not None else None,
                    "commentary_author": commentary_author,
                    "tradition": record.get("tradition"),
                    "language_tags": record.get("language_tags"),
                    "format": "jsonl_verse",
                },
                source=source,
            )
            yield chunk_id, doc, metadata


_CHAPTER_HDR = re.compile(r"^\s*##\s+Chapter\s+(?P<chapter>[\w.]+)\s*$", re.IGNORECASE)
_VERSE_HDR = re.compile(r"^\s*###\s+Verse\s+(?P<verse>[\w.]+)\s*$", re.IGNORECASE)


def chunk_structured_text(path: Path, *, source: str | None = None) -> Iterator[VerseChunk]:
    """Parse a markdown-ish file with `## Chapter X` and `### Verse Y` markers."""
    src = source or path.stem
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    chapter: str | None = None
    verse: str | None = None
    buffer: list[str] = []
    idx = 0

    def flush() -> Iterator[VerseChunk]:
        body = "\n".join(buffer).strip()
        if not body:
            return iter(())
        chunk_id = ":".join(p for p in [src, chapter or "", verse or str(idx)] if p)
        meta = _flatten_metadata(
            {"chapter": chapter, "verse": verse, "format": "structured_text"},
            source=src,
        )
        return iter([(chunk_id, body, meta)])

    for line in lines:
        chap_match = _CHAPTER_HDR.match(line)
        if chap_match:
            yield from flush()
            buffer = []
            chapter = chap_match.group("chapter")
            verse = None
            idx += 1
            continue
        verse_match = _VERSE_HDR.match(line)
        if verse_match:
            yield from flush()
            buffer = []
            verse = verse_match.group("verse")
            idx += 1
            continue
        buffer.append(line)
    yield from flush()


def chunk_paragraphs(
    path: Path, *, source: str | None = None, min_chars: int = 80
) -> Iterator[VerseChunk]:
    """Split on blank lines; drop tiny chunks. Useful for prose."""
    src = source or path.stem
    text = path.read_text(encoding="utf-8")
    for idx, raw in enumerate(text.split("\n\n")):
        candidate = raw.strip()
        if len(candidate) < min_chars:
            continue
        chunk_id = f"{src}:p{idx}"
        meta = _flatten_metadata({"format": "paragraph"}, source=src)
        yield chunk_id, candidate, meta


def chunk_pdf(path: Path, *, source: str | None = None, min_chars: int = 120) -> Iterator[VerseChunk]:
    """Extract text from a PDF and yield paragraph-sized chunks.

    Uses pypdf if available. Layout-naive: works fine for prose
    commentary; verse-aligned PDFs should be hand-curated to JSONL.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "PDF ingestion requires pypdf. Install with `pip install pypdf` "
            "(it's not a default dependency to keep the base install slim)."
        ) from exc

    src = source or path.stem
    reader = PdfReader(str(path))
    for page_idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - per-page failures shouldn't kill ingestion
            logger.warning("Failed to extract page %d of %s: %s", page_idx, path, exc)
            continue
        for para_idx, raw in enumerate(text.split("\n\n")):
            candidate = raw.strip()
            if len(candidate) < min_chars:
                continue
            chunk_id = f"{src}:page{page_idx}:p{para_idx}"
            meta = _flatten_metadata(
                {"page": page_idx, "format": "pdf_paragraph"}, source=src
            )
            yield chunk_id, candidate, meta
