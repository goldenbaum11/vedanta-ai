#!/usr/bin/env python3
"""Fetch the full Bhagavad Gita corpus and transform it to our JSONL schema.

Source: https://github.com/ravisiyer/gita-data (The Unlicense / public domain),
itself derived from https://github.com/gita/gita.

Produces ``data/vedic_texts/bhagavad_gita.jsonl`` with:
  - one row per verse: Sanskrit + IAST + English translation + word_meanings
  - one row per verse-commentary pair from configured commentators

Idempotent: caches raw API responses under ``data/_cache/gita-data/`` so
re-runs don't hammer the upstream host.

Usage:
    python3 scripts/fetch_gita.py [--reset]

After running, ingest with:
    python3 scripts/ingest_corpus.py --collection vedic_texts \\
        --dir data/vedic_texts/ --reset
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "vedic_texts"
CACHE_DIR = REPO_ROOT / "data" / "_cache" / "gita-data"
OUTPUT_PATH = DATA_DIR / "bhagavad_gita.jsonl"

API_BASE = "https://ravisiyer.github.io/gita-data/v1"

# Author IDs from gita-data/authors.json. We pick:
#   - 19: Swami Gambirananda (Advaita; preferred translator per our system prompt)
#   - 16: Swami Sivananda (Divine Life Society; broad accessible English translation)
PRIMARY_TRANSLATOR_ID = 19
PRIMARY_TRANSLATOR_NAME = "Swami Gambirananda"
SECONDARY_TRANSLATOR_ID = 16
SECONDARY_TRANSLATOR_NAME = "Swami Sivananda"

# Commentaries to pull (author_id, language_id, label, tradition).
# language_id 1 == English in the source dataset.
COMMENTARIES = [
    (16, 1, "Swami Sivananda", "Advaita Vedanta (Divine Life Society)"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("fetch_gita")


@dataclass(frozen=True)
class VerseRow:
    chapter: str
    verse: str
    sanskrit: str
    iast: str
    word_meanings: str
    translation_primary: str
    translation_secondary: str


def _fetch(url: str, cache_path: Path) -> bytes:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        logger.info("cache hit: %s", cache_path.relative_to(REPO_ROOT))
        return cache_path.read_bytes()
    logger.info("fetching %s", url)
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read()
    cache_path.write_bytes(body)
    return body


def _fetch_json(url: str, cache_path: Path) -> Any:
    return json.loads(_fetch(url, cache_path).decode("utf-8"))


def _load_verses() -> list[dict[str, Any]]:
    return _fetch_json(f"{API_BASE}/verse.json", CACHE_DIR / "verse.json")


def _load_translations() -> list[dict[str, Any]]:
    return _fetch_json(f"{API_BASE}/translation.json", CACHE_DIR / "translation.json")


def _load_commentary(author_id: int, lang_id: int, chapter: int) -> list[dict[str, Any]]:
    rel = f"commentaries/author{author_id}/lang{lang_id}/chapter{chapter}.json"
    return _fetch_json(f"{API_BASE}/{rel}", CACHE_DIR / rel)


def _strip(text: str | None) -> str:
    if not text:
        return ""
    # Source data has lots of stray newlines and the verse-locator suffix
    # (e.g. "।।1.1।।") embedded in the Sanskrit and Hindi translations.
    # We keep them in Sanskrit (they're scriptural) but strip excess
    # whitespace.
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _build_translation_index(
    rows: Iterable[dict[str, Any]],
) -> dict[tuple[int, int], str]:
    """Map (verse_id, author_id) → English translation text."""
    index: dict[tuple[int, int], str] = {}
    for row in rows:
        if row.get("lang") != "english":
            continue
        verse_id = row.get("verse_id")
        author_id = row.get("author_id")
        text = _strip(row.get("description"))
        if not (isinstance(verse_id, int) and isinstance(author_id, int) and text):
            continue
        index[(verse_id, author_id)] = text
    return index


def _emit_verse(row: VerseRow) -> dict[str, Any]:
    return {
        "source": "Bhagavad Gita",
        "chapter": row.chapter,
        "verse": row.verse,
        "sanskrit": row.sanskrit,
        "iast": row.iast,
        "translation": row.translation_primary,
        "translation_alternate": row.translation_secondary or None,
        "word_meanings": row.word_meanings or None,
        "translator": PRIMARY_TRANSLATOR_NAME,
        "language_tags": ["sanskrit", "iast", "english"],
    }


def _emit_commentary(
    *,
    chapter: str,
    verse: str,
    author: str,
    tradition: str,
    text: str,
) -> dict[str, Any]:
    return {
        "source": "Bhagavad Gita",
        "chapter": chapter,
        "verse": verse,
        "commentary": text,
        "commentary_author": author,
        "tradition": tradition,
        "language_tags": ["english"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the cached download files before fetching.",
    )
    args = parser.parse_args()

    if args.reset and CACHE_DIR.exists():
        logger.info("clearing cache: %s", CACHE_DIR)
        for p in CACHE_DIR.rglob("*"):
            if p.is_file():
                p.unlink()

    logger.info("Stage 1/4: loading verses")
    verses = _load_verses()
    logger.info("  %d verse rows", len(verses))

    logger.info("Stage 2/4: loading translations")
    translations = _load_translations()
    logger.info("  %d translation rows", len(translations))
    translation_index = _build_translation_index(translations)

    logger.info("Stage 3/4: loading commentaries")
    commentary_index: dict[tuple[int, int, int], dict[int, str]] = {}
    for author_id, lang_id, label, _tradition in COMMENTARIES:
        chapter_map: dict[int, str] = {}
        for chapter in range(1, 19):
            rows = _load_commentary(author_id, lang_id, chapter)
            for r in rows:
                if r.get("verse_id") and r.get("description"):
                    text = _strip(r["description"])
                    if text:
                        commentary_index.setdefault(
                            (author_id, lang_id, chapter), {}
                        )[r["verse_id"]] = text
        loaded = sum(len(v) for v in commentary_index.values() if v)
        logger.info("  %s loaded (cumulative entries: %d)", label, loaded)

    logger.info("Stage 4/4: writing %s", OUTPUT_PATH.relative_to(REPO_ROOT))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    verse_count = 0
    commentary_count = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for verse_doc in verses:
            verse_id = verse_doc.get("id")
            chapter = verse_doc.get("chapter_number")
            verse_no = verse_doc.get("verse_number")
            if not isinstance(verse_id, int):
                continue
            sanskrit = _strip(verse_doc.get("text"))
            iast = _strip(verse_doc.get("transliteration"))
            word_meanings = _strip(verse_doc.get("word_meanings"))
            translation_primary = translation_index.get(
                (verse_id, PRIMARY_TRANSLATOR_ID), ""
            )
            translation_secondary = translation_index.get(
                (verse_id, SECONDARY_TRANSLATOR_ID), ""
            )
            if not (sanskrit and (translation_primary or translation_secondary)):
                logger.debug("skipping incomplete verse_id=%s", verse_id)
                continue
            row = VerseRow(
                chapter=str(chapter),
                verse=str(verse_no),
                sanskrit=sanskrit,
                iast=iast,
                word_meanings=word_meanings,
                translation_primary=translation_primary
                or translation_secondary,
                translation_secondary=translation_secondary
                if translation_primary
                else "",
            )
            out.write(json.dumps(_emit_verse(row), ensure_ascii=False) + "\n")
            verse_count += 1

            for author_id, lang_id, label, tradition in COMMENTARIES:
                chapter_table = commentary_index.get(
                    (author_id, lang_id, int(chapter)), {}
                )
                commentary_text = chapter_table.get(verse_id)
                if not commentary_text:
                    continue
                out.write(
                    json.dumps(
                        _emit_commentary(
                            chapter=str(chapter),
                            verse=str(verse_no),
                            author=label,
                            tradition=tradition,
                            text=commentary_text,
                        ),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                commentary_count += 1

    print(
        f"Wrote {verse_count} verses + {commentary_count} commentaries "
        f"({verse_count + commentary_count} total chunks) to {OUTPUT_PATH.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
