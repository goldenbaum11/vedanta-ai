#!/usr/bin/env python3
"""Fetch Principal Upanishad corpus and transform to our JSONL schema.

Sources (both attributed in each emitted row):

1. **atmabodha/Vedanta_Datasets** (released for ML/Vedanta analysis):
   - Isha (Isavasya) Upanishad: Sanskrit + English translation
   - Katha Upanishad: Sanskrit + English translation
   - Mandukya Upanishad: Sanskrit + English translation

2. **hrgupta/indian-scriptures** (MIT licensed):
   - Kena, Mundaka, Brihadaranyaka, Chandogya: Sanskrit-only

The full English translation for the hrgupta-sourced Upanishads is a
follow-up pass; the agent's anti-fabrication guard prevents it from
inventing translations that aren't in the corpus.

Idempotent: caches raw downloads under ``data/_cache/upanishads/``.

Usage:
    python3 scripts/fetch_upanishads.py [--reset]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import urllib.request
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "vedic_texts"
CACHE_DIR = REPO_ROOT / "data" / "_cache" / "upanishads"
OUTPUT_PATH = DATA_DIR / "upanishads.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("fetch_upanishads")


@dataclass(frozen=True)
class AtmabodhaSource:
    label: str  # canonical name we emit in `source`
    url: str
    chapter_col: str
    has_translation: bool = True
    attribution: str = (
        "atmabodha/Vedanta_Datasets (used per repo README's ML-research grant)"
    )


@dataclass(frozen=True)
class HrguptaSource:
    label: str
    url: str
    attribution: str = "hrgupta/indian-scriptures (MIT)"


ATMABODHA_BASE = (
    "https://raw.githubusercontent.com/atmabodha/Vedanta_Datasets/master/Upanishads"
)
HRGUPTA_BASE = (
    "https://raw.githubusercontent.com/hrgupta/indian-scriptures/master"
    "/data/processed/upanishads"
)

ATMABODHA_SOURCES = [
    AtmabodhaSource(
        label="Isha Upanishad",
        url=f"{ATMABODHA_BASE}/Upanishad_Isavasya.csv",
        chapter_col="Chapter",
    ),
    AtmabodhaSource(
        label="Katha Upanishad",
        url=f"{ATMABODHA_BASE}/Upanishad_Katha.csv",
        chapter_col="Chapter/Valli",
    ),
    AtmabodhaSource(
        label="Mandukya Upanishad",
        url=f"{ATMABODHA_BASE}/Upanishad_Mandukya.csv",
        chapter_col="Chapter",
    ),
]

HRGUPTA_SOURCES = [
    HrguptaSource(
        label="Kena Upanishad", url=f"{HRGUPTA_BASE}/kena_upanishad.csv"
    ),
    HrguptaSource(
        label="Mundaka Upanishad", url=f"{HRGUPTA_BASE}/mundaka_upanishad.csv"
    ),
    HrguptaSource(
        label="Brihadaranyaka Upanishad",
        url=f"{HRGUPTA_BASE}/brihadaranyaka_upanishad.csv",
    ),
    HrguptaSource(
        label="Prashna Upanishad",
        url=f"{HRGUPTA_BASE}/prasna_upanishad.csv",
    ),
    HrguptaSource(
        label="Aitareya Upanishad",
        url=f"{HRGUPTA_BASE}/aitereya_upanishad.csv",
    ),
    HrguptaSource(
        label="Taittiriya Upanishad",
        url=f"{HRGUPTA_BASE}/taittiriya_upanishad.csv",
    ),
    HrguptaSource(
        label="Shvetashvatara Upanishad",
        url=f"{HRGUPTA_BASE}/svetashvatra_upanishad.csv",
    ),
    # Note: Chandogya is not present in hrgupta/indian-scriptures.
    # Tracked as a follow-up corpus task in README.
]


def _cache_path(url: str) -> Path:
    safe = url.split("/")[-1]
    return CACHE_DIR / safe


def _fetch_text(url: str) -> str:
    cache = _cache_path(url)
    if cache.exists():
        logger.info("cache hit: %s", cache.relative_to(REPO_ROOT))
        return cache.read_text(encoding="utf-8")
    cache.parent.mkdir(parents=True, exist_ok=True)
    logger.info("fetching %s", url)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch failed for %s: %s", url, exc)
        return ""
    cache.write_text(body, encoding="utf-8")
    return body


def _strip(text: str | None) -> str:
    if not text:
        return ""
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _parse_chapter_verse(raw: str) -> tuple[str, str]:
    """`1.1` → ('1', '1'); `1` → ('1', '1'); `2.3.4` → ('2.3', '4')."""
    raw = raw.strip()
    if not raw:
        return ("1", "1")
    parts = raw.split(".")
    if len(parts) >= 2:
        return (".".join(parts[:-1]), parts[-1])
    return (raw, "1")


def _emit_with_translation(
    *,
    source: str,
    chapter: str,
    verse: str,
    sanskrit: str,
    translation: str,
    attribution: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "chapter": chapter,
        "verse": verse,
        "sanskrit": sanskrit,
        "translation": translation,
        "language_tags": ["sanskrit", "english"],
        "attribution": attribution,
    }


def _emit_sanskrit_only(
    *,
    source: str,
    chapter: str,
    verse: str,
    sanskrit: str,
    attribution: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "chapter": chapter,
        "verse": verse,
        "sanskrit": sanskrit,
        "language_tags": ["sanskrit"],
        "attribution": attribution,
        "english_translation_status": "pending",
    }


# Matches the standard verse marker like "।। 1.1.1 ।।" or "॥ 2.3 ॥"
_VERSE_NUM_RE = re.compile(r"[।॥]+\s*([0-9.]+)\s*[।॥]+")


def _process_atmabodha(src: AtmabodhaSource) -> list[dict[str, Any]]:
    body = _fetch_text(src.url)
    if not body:
        return []
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(StringIO(body))
    for row in reader:
        chapter_raw = (row.get(src.chapter_col) or "").strip()
        verse_raw = (row.get("Verse") or "").strip()
        sanskrit = _strip(row.get("Sanskrit"))
        translation = _strip(row.get("Translation"))
        if not (chapter_raw and verse_raw and sanskrit):
            continue
        chapter = chapter_raw
        verse = verse_raw
        rows.append(
            _emit_with_translation(
                source=src.label,
                chapter=chapter,
                verse=verse,
                sanskrit=sanskrit,
                translation=translation,
                attribution=src.attribution,
            )
        )
    return rows


def _process_hrgupta(src: HrguptaSource) -> list[dict[str, Any]]:
    body = _fetch_text(src.url)
    if not body:
        return []
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(StringIO(body))
    for row in reader:
        mantra = _strip(row.get("mantra") or "")
        number = (row.get("number") or "").strip()
        if not mantra:
            continue
        # Pull the canonical chapter.verse pattern from the marker if present.
        match = _VERSE_NUM_RE.search(number) or _VERSE_NUM_RE.search(mantra)
        if match:
            chapter, verse = _parse_chapter_verse(match.group(1))
        else:
            # Some entries are intro/shanti mantras with no number; skip
            # them rather than emit a fake reference that the verse-locator
            # header would mislabel.
            continue
        rows.append(
            _emit_sanskrit_only(
                source=src.label,
                chapter=chapter,
                verse=verse,
                sanskrit=mantra,
                attribution=src.attribution,
            )
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear the local download cache before fetching.",
    )
    args = parser.parse_args()

    if args.reset and CACHE_DIR.exists():
        logger.info("clearing cache: %s", CACHE_DIR)
        for p in CACHE_DIR.rglob("*"):
            if p.is_file():
                p.unlink()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    bilingual = 0
    sanskrit_only = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        logger.info("Stage 1/2: atmabodha sources (Sanskrit + English)")
        for src in ATMABODHA_SOURCES:
            rows = _process_atmabodha(src)
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            logger.info("  %s: %d rows", src.label, len(rows))
            total += len(rows)
            bilingual += len(rows)

        logger.info("Stage 2/2: hrgupta sources (Sanskrit only)")
        for src in HRGUPTA_SOURCES:
            rows = _process_hrgupta(src)
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            logger.info("  %s: %d rows", src.label, len(rows))
            total += len(rows)
            sanskrit_only += len(rows)

    print(
        f"Wrote {total} Upanishad chunks to "
        f"{OUTPUT_PATH.relative_to(REPO_ROOT)} "
        f"({bilingual} bilingual, {sanskrit_only} Sanskrit-only)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
