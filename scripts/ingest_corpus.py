"""One-shot corpus ingestion runner.

Usage:
    python scripts/ingest_corpus.py --collection vedic_texts --dir data/vedic_texts/

Phase 1 supports plain-text / markdown only. Phase 2 will add PDFs and
verse-aware chunking for Sanskrit sources.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.knowledge.ingest import ingest_directory  # noqa: E402
from backend.rag.vector_store import COLLECTION_NAMES, ensure_collections  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a corpus into ChromaDB.")
    parser.add_argument(
        "--collection",
        required=True,
        choices=COLLECTION_NAMES,
        help="Target ChromaDB collection.",
    )
    parser.add_argument(
        "--dir",
        required=True,
        type=Path,
        help="Directory containing text/markdown files to ingest.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    ensure_collections()
    total = ingest_directory(collection_name=args.collection, directory=args.dir)
    print(f"Ingested {total} chunks into '{args.collection}' from {args.dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
