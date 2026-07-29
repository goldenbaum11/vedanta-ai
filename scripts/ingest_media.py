"""One-shot media ingestion runner: Whisper transcription + Tesseract OCR
into the `media_index` ChromaDB collection.

Mirrors `ingest_corpus.py`'s directory-walk + idempotent-batch-add shape,
but the "chunkers" here consume already-processed model output
(transcribed segments, OCR text) rather than reading files directly —
see `backend/knowledge/media_chunker.py`.

Examples:
    # Transcribe/OCR everything under data/media/, auto-detected by extension
    python scripts/ingest_media.py --dir data/media/

    # Just re-run OCR at a different chunk size, resetting the collection
    python scripts/ingest_media.py --dir data/media/scans/ --reset
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.knowledge.media_chunker import chunk_ocr_text, chunk_transcript  # noqa: E402
from backend.media import ocr, transcribe  # noqa: E402
from backend.rag.vector_store import add_documents, ensure_collections  # noqa: E402

logger = logging.getLogger("ingest_media")

AUDIO_VIDEO_EXT = {".mp3", ".wav", ".m4a", ".mp4", ".mov", ".webm", ".ogg", ".flac"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

# Whisper language codes worth flagging for a human to route through the
# vedic_scholar agent instead — the media agent transcribes speech, it
# doesn't verify Sanskrit/Hindi content against the loaded corpus.
_FLAG_LANGUAGES = {"hi", "sa", "ne"}


def _iter_media_files(directory: Path) -> list[Path]:
    return sorted(
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_VIDEO_EXT | IMAGE_EXT
    )


async def _process_file(
    path: Path, *, window_seconds: float
) -> list[tuple[str, str, dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix in AUDIO_VIDEO_EXT:
        result = await transcribe.transcribe_file(path)
        if result.language in _FLAG_LANGUAGES:
            logger.info(
                "%s detected as language=%r — consider routing through "
                "vedic_scholar for verse-accuracy review.",
                path.name,
                result.language,
            )
        return list(
            chunk_transcript(
                result.segments,
                source=path.stem,
                language=result.language,
                window_seconds=window_seconds,
            )
        )
    text = await ocr.ocr_image(path)
    return list(chunk_ocr_text(text, source=path.stem))


async def _run(
    *, collection: str, directory: Path, window_seconds: float, reset: bool
) -> int:
    if not directory.exists():
        raise FileNotFoundError(f"Media directory does not exist: {directory}")

    files = _iter_media_files(directory)
    if not files:
        logger.warning("No supported media files found under %s", directory)
        return 0

    needs_whisper = any(p.suffix.lower() in AUDIO_VIDEO_EXT for p in files)
    needs_ocr = any(p.suffix.lower() in IMAGE_EXT for p in files)
    if needs_whisper and not transcribe.is_available():
        logger.error(
            "Found audio/video files but whisper isn't installed — "
            "those will be skipped. %s",
            transcribe.INSTALL_HINT,
        )
    if needs_ocr and not ocr.is_available():
        logger.error(
            "Found image files but pytesseract/tesseract isn't available — "
            "those will be skipped. %s",
            ocr.INSTALL_HINT,
        )

    if reset:
        from backend.rag.vector_store import reset_collection

        logger.info("Resetting collection: %s", collection)
        reset_collection(collection)
    else:
        ensure_collections()

    total = 0
    for path in files:
        suffix = path.suffix.lower()
        if suffix in AUDIO_VIDEO_EXT and not transcribe.is_available():
            continue
        if suffix in IMAGE_EXT and not ocr.is_available():
            continue
        try:
            chunks = await _process_file(path, window_seconds=window_seconds)
        except Exception as exc:  # noqa: BLE001 - per-file failures shouldn't kill the run
            logger.error("Failed to process %s: %s", path, exc)
            continue
        if not chunks:
            logger.info("No chunks produced from %s", path)
            continue
        ids = [c[0] for c in chunks]
        docs = [c[1] for c in chunks]
        metas = [c[2] for c in chunks]
        added = add_documents(
            collection_name=collection, documents=docs, metadatas=metas, ids=ids
        )
        logger.info("Added %d/%d chunks from %s", added, len(chunks), path)
        total += added

    logger.info("Ingested %d total chunks into '%s'.", total, collection)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe/OCR a media directory into ChromaDB."
    )
    parser.add_argument(
        "--collection",
        default="media_index",
        help="Target ChromaDB collection (default: media_index).",
    )
    parser.add_argument(
        "--dir", required=True, type=Path, help="Directory of media files."
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=45.0,
        help="Transcript chunk window size in seconds (default: 45).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate the collection before ingesting.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )

    total = asyncio.run(
        _run(
            collection=args.collection,
            directory=args.dir,
            window_seconds=args.window_seconds,
            reset=args.reset,
        )
    )
    print(f"Ingested {total} chunks into '{args.collection}' from {args.dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
