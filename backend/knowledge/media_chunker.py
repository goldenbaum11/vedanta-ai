"""Chunkers for processed media (Whisper transcripts, OCR text) headed
into the `media_index` ChromaDB collection.

Kept separate from `knowledge/chunker.py` (which handles text corpora
formats: jsonl/md/txt/pdf read straight off disk) because these work off
already-processed model output — timestamped segments, OCR strings —
rather than files.
"""

from __future__ import annotations

from typing import Any, Iterator

from ..media.transcribe import TranscriptSegment

MediaChunk = tuple[str, str, dict[str, Any]]


def chunk_transcript(
    segments: list[TranscriptSegment],
    *,
    source: str,
    language: str = "",
    window_seconds: float = 45.0,
) -> Iterator[MediaChunk]:
    """Group consecutive Whisper segments into ~`window_seconds` windows.

    Raw Whisper segments are usually a few seconds each — too granular
    to be useful retrieval units, and too numerous to index one-by-one.
    Windowing keeps each chunk long enough to carry a complete thought
    while preserving start/end timestamps so citations can link back to
    the exact point in the recording.
    """
    if not segments:
        return

    def _finalize(buf: list[TranscriptSegment]) -> MediaChunk | None:
        body = " ".join(s.text.strip() for s in buf if s.text.strip()).strip()
        if not body:
            return None
        start, end = buf[0].start, buf[-1].end
        chunk_id = f"{source}:{start:.1f}-{end:.1f}"
        # Locator baked into the document body (not just metadata) so it
        # survives into the LLM prompt via retriever.format_context_block,
        # which only special-cases chapter/verse headers — same trick
        # chunker._build_verse_document uses for "[Bhagavad Gita 2.47]".
        text = f"[{source} {start:.1f}-{end:.1f}s]\n{body}"
        metadata: dict[str, Any] = {
            "source": source,
            "start": round(start, 2),
            "end": round(end, 2),
            "format": "media_transcript",
        }
        if language:
            metadata["language"] = language
        return chunk_id, text, metadata

    buffer: list[TranscriptSegment] = []
    for seg in segments:
        if buffer and (seg.end - buffer[0].start) > window_seconds:
            chunk = _finalize(buffer)
            if chunk:
                yield chunk
            buffer = []
        buffer.append(seg)
    chunk = _finalize(buffer)
    if chunk:
        yield chunk


def chunk_ocr_text(
    text: str, *, source: str, min_chars: int = 40
) -> Iterator[MediaChunk]:
    """Split OCR output on blank lines; drop fragments too short to be useful.

    OCR text has no timestamps, so chunk ids are just a running index.
    """
    for idx, raw in enumerate(text.split("\n\n")):
        candidate = raw.strip()
        if len(candidate) < min_chars:
            continue
        chunk_id = f"{source}:ocr{idx}"
        body = f"[{source}]\n{candidate}"
        metadata: dict[str, Any] = {"source": source, "format": "media_ocr"}
        yield chunk_id, body, metadata
