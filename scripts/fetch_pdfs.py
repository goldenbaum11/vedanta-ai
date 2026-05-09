#!/usr/bin/env python3
"""Fetch the public-domain commentary PDFs used by the corpus.

PDFs are *not* committed to the repo because they're (a) heavy binary
content, and (b) jurisdictionally ambiguous on US copyright even when
clearly PD in India (URAA-restored copyright on works first published
abroad before 1996). This script lets you reproduce the corpus locally.

After running, ingest with:
    python3 scripts/ingest_corpus.py --collection vedic_texts \\
        --dir data/vedic_texts/

Usage:
    python3 scripts/fetch_pdfs.py [--reset]
"""

from __future__ import annotations

import argparse
import logging
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = REPO_ROOT / "data" / "vedic_texts"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("fetch_pdfs")


@dataclass(frozen=True)
class PdfSource:
    filename: str
    url: str
    description: str


SOURCES = [
    PdfSource(
        filename="aurobindo_isha_upanishad_1945.pdf",
        url=(
            "https://archive.org/download/"
            "nnaw_isha-upanishad-by-sri-aurobindo-1945-calcutta-arya-publishing-house/"
            "Isha%20Upanishad%20By%20Sri%20Aurobindo%201945%20Calcutta%20-%20"
            "Arya%20Publishing%20House_text.pdf"
        ),
        description=(
            "Sri Aurobindo's commentary on the Isha Upanishad (Calcutta, "
            "Arya Publishing House, 1945). Public domain in India "
            "(life + 60 years; Aurobindo died 1950). 5.5 MB text-extracted."
        ),
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Re-download even if the file exists locally.",
    )
    args = parser.parse_args()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for src in SOURCES:
        target = TARGET_DIR / src.filename
        if target.exists() and not args.reset:
            logger.info("already present, skipping: %s", target.relative_to(REPO_ROOT))
            continue
        logger.info("downloading %s", src.url)
        logger.info("  → %s", target.relative_to(REPO_ROOT))
        try:
            urllib.request.urlretrieve(src.url, str(target))
        except Exception as exc:  # noqa: BLE001
            logger.error("download failed: %s", exc)
            return 1
        size_mb = target.stat().st_size / (1024 * 1024)
        logger.info("  done (%.1f MB)", size_mb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
