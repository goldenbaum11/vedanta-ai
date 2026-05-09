"""One-shot corpus ingestion runner.

Examples:
    # Ingest a directory, auto-detecting format per file
    python scripts/ingest_corpus.py --collection vedic_texts --dir data/vedic_texts/

    # Force JSONL format and reset the collection first (use when you've
    # changed EMBEDDING_PROVIDER and the old vectors are incompatible).
    python scripts/ingest_corpus.py \\
        --collection vedic_texts \\
        --dir data/vedic_texts/ \\
        --format jsonl \\
        --reset
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

FORMATS = ("jsonl", "structured_text", "paragraphs", "pdf")


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
        help="Directory containing source files to ingest.",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default=None,
        help="Force a specific format. Default: auto-detect by extension.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate the collection before ingesting "
        "(required when changing EMBEDDING_PROVIDER).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    if not args.reset:
        ensure_collections()
    total = ingest_directory(
        collection_name=args.collection,
        directory=args.dir,
        format_override=args.format,
        reset=args.reset,
    )
    print(f"Ingested {total} chunks into '{args.collection}' from {args.dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
