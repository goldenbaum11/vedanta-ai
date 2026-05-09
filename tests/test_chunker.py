"""Chunker tests.

Cover the four chunker entry points:
- `chunk_jsonl_verses`: schema mapping, locator headers, metadata flattening.
- `chunk_structured_text`: chapter/verse markdown headers.
- `chunk_paragraphs`: blank-line splitting + min-char filter.
- `chunk_pdf`: smoke-test via a generated tiny PDF (skipped if pypdf
  isn't installed in the environment).

These functions are pure — no env, no I/O beyond the temp file — so we
don't need any fixtures beyond `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.knowledge import chunker


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_jsonl_verses_emits_locator_header_and_full_metadata(tmp_path: Path) -> None:
    src = tmp_path / "gita.jsonl"
    _write_jsonl(
        src,
        [
            {
                "source": "Bhagavad Gita",
                "chapter": "2",
                "verse": "47",
                "sanskrit": "कर्मण्येवाधिकारस्ते",
                "iast": "karmaṇy evādhikāras te",
                "translation": "You have a right to action only...",
                "commentary": "Action without attachment.",
                "commentary_author": "Shankaracharya",
                "tradition": "Advaita",
                "language_tags": ["sanskrit", "iast", "english"],
            }
        ],
    )

    chunks = list(chunker.chunk_jsonl_verses(src))
    assert len(chunks) == 1
    chunk_id, document, metadata = chunks[0]
    assert chunk_id == "Bhagavad Gita:2:47:Shankaracharya"
    assert document.startswith("[Bhagavad Gita 2.47] — Shankaracharya")
    assert "Sanskrit:" in document
    assert "IAST:" in document
    assert "Translation:" in document
    assert "Shankaracharya:" in document
    assert metadata["source"] == "Bhagavad Gita"
    assert metadata["chapter"] == "2"
    assert metadata["verse"] == "47"
    assert metadata["language_tags"] == "sanskrit, iast, english"
    assert metadata["format"] == "jsonl_verse"


def test_jsonl_verses_skips_blank_lines_and_invalid_json(tmp_path: Path) -> None:
    src = tmp_path / "noisy.jsonl"
    src.write_text(
        "\n"
        "# this is a comment\n"
        "{\"source\": \"X\", \"chapter\": \"1\", \"verse\": \"1\", \"translation\": \"good\"}\n"
        "{not valid json\n"
        "\n",
        encoding="utf-8",
    )
    chunks = list(chunker.chunk_jsonl_verses(src))
    assert len(chunks) == 1
    assert chunks[0][0] == "X:1:1"


def test_jsonl_verses_falls_back_to_path_stem_when_no_source(tmp_path: Path) -> None:
    """When `source` is missing, the chunker uses the file stem and produces
    a stable id from whatever locator parts exist (path stem alone here)."""
    src = tmp_path / "fallback.jsonl"
    _write_jsonl(src, [{"translation": "orphan verse"}])
    chunks = list(chunker.chunk_jsonl_verses(src))
    assert len(chunks) == 1
    chunk_id, document, metadata = chunks[0]
    assert chunk_id == "fallback"
    assert metadata["source"] == "fallback"
    assert "Translation:" in document


def test_structured_text_picks_chapter_and_verse_from_headers(tmp_path: Path) -> None:
    src = tmp_path / "doc.md"
    src.write_text(
        "## Chapter 1\n"
        "### Verse 1\n"
        "First verse body.\n"
        "More body.\n"
        "\n"
        "### Verse 2\n"
        "Second verse body.\n",
        encoding="utf-8",
    )
    chunks = list(chunker.chunk_structured_text(src, source="Doc"))
    assert len(chunks) == 2
    first, second = chunks
    assert first[2]["chapter"] == "1"
    assert first[2]["verse"] == "1"
    assert "First verse body" in first[1]
    assert second[2]["verse"] == "2"
    assert "Second verse body" in second[1]


def test_paragraph_chunker_drops_short_paragraphs(tmp_path: Path) -> None:
    src = tmp_path / "prose.txt"
    src.write_text(
        "Tiny paragraph.\n\nThis paragraph is intentionally long so it survives the eighty-character minimum filter applied by the chunker.\n",
        encoding="utf-8",
    )
    chunks = list(chunker.chunk_paragraphs(src))
    assert len(chunks) == 1
    assert "This paragraph is intentionally long" in chunks[0][1]


def test_pdf_chunker_smoke(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    src = tmp_path / "tiny.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with src.open("wb") as f:
        writer.write(f)

    chunks = list(chunker.chunk_pdf(src, source="tiny"))
    assert chunks == []
    assert pypdf.__version__
