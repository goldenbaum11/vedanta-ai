"""Tests for the media processing pipeline (Phase 6).

Covers:
- `media_chunker.chunk_transcript` / `chunk_ocr_text`: pure functions, no
  env or I/O, so no fixtures needed beyond plain data.
- `media.transcribe` / `media.ocr`: the "backend not installed" path,
  which is exactly the state of this dev/CI environment (neither
  openai-whisper nor pytesseract is installed by default — see
  backend/requirements.txt). We don't attempt real transcription/OCR
  here; that would require the heavy optional deps and is out of scope
  for the hermetic offline suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.knowledge.media_chunker import chunk_ocr_text, chunk_transcript
from backend.media import ocr, transcribe
from backend.media.transcribe import TranscriptSegment

# -- chunk_transcript -------------------------------------------------------


def test_chunk_transcript_groups_segments_into_windows() -> None:
    segments = [
        TranscriptSegment(start=0.0, end=5.0, text="Welcome everyone."),
        TranscriptSegment(start=5.0, end=20.0, text="Today we discuss karma yoga."),
        TranscriptSegment(start=20.0, end=50.0, text="This starts a new window."),
    ]
    chunks = list(chunk_transcript(segments, source="lecture1", language="en", window_seconds=30.0))

    assert len(chunks) == 2
    first_id, first_text, first_meta = chunks[0]
    assert first_id == "lecture1:0.0-20.0"
    assert "Welcome everyone." in first_text
    assert "Today we discuss karma yoga." in first_text
    assert first_text.startswith("[lecture1 0.0-20.0s]")
    assert first_meta == {
        "source": "lecture1",
        "start": 0.0,
        "end": 20.0,
        "format": "media_transcript",
        "language": "en",
    }

    second_id, second_text, _ = chunks[1]
    assert second_id == "lecture1:20.0-50.0"
    assert "new window" in second_text


def test_chunk_transcript_empty_input() -> None:
    assert list(chunk_transcript([], source="empty")) == []


def test_chunk_transcript_drops_blank_segments() -> None:
    segments = [
        TranscriptSegment(start=0.0, end=1.0, text="   "),
        TranscriptSegment(start=1.0, end=2.0, text=""),
    ]
    assert list(chunk_transcript(segments, source="silence")) == []


def test_chunk_transcript_omits_language_when_unset() -> None:
    segments = [TranscriptSegment(start=0.0, end=1.0, text="hello")]
    _, _, meta = next(chunk_transcript(segments, source="s"))
    assert "language" not in meta


# -- chunk_ocr_text -----------------------------------------------------------


def test_chunk_ocr_text_splits_on_blank_lines_and_filters_short() -> None:
    text = (
        "This is a long enough paragraph to survive the min_chars filter.\n\n"
        "short\n\n"
        "Another sufficiently long paragraph of scanned manuscript text."
    )
    chunks = list(chunk_ocr_text(text, source="manuscript1"))
    assert len(chunks) == 2
    ids = [c[0] for c in chunks]
    assert ids == ["manuscript1:ocr0", "manuscript1:ocr2"]
    assert chunks[0][1].startswith("[manuscript1]")
    assert chunks[0][2] == {"source": "manuscript1", "format": "media_ocr"}


def test_chunk_ocr_text_empty() -> None:
    assert list(chunk_ocr_text("", source="blank")) == []


# -- transcribe.py / ocr.py: dependency-unavailable path ---------------------


def test_whisper_reports_unavailable_in_this_environment() -> None:
    assert transcribe.is_available() is False


def test_tesseract_reports_unavailable_in_this_environment() -> None:
    assert ocr.is_available() is False


async def test_transcribe_file_raises_clear_error_when_unavailable(tmp_path: Path) -> None:
    fake_audio = tmp_path / "lecture.mp3"
    fake_audio.write_bytes(b"not a real audio file")
    with pytest.raises(RuntimeError, match="openai-whisper"):
        await transcribe.transcribe_file(fake_audio)


async def test_transcribe_file_missing_file_still_checked() -> None:
    # Dependency check happens before the file-existence check; either
    # error is acceptable, but it must not silently succeed.
    with pytest.raises((RuntimeError, FileNotFoundError)):
        await transcribe.transcribe_file(Path("/nonexistent/lecture.mp3"))


async def test_ocr_image_raises_clear_error_when_unavailable(tmp_path: Path) -> None:
    fake_image = tmp_path / "scan.png"
    fake_image.write_bytes(b"not a real image file")
    with pytest.raises(RuntimeError, match="pytesseract"):
        await ocr.ocr_image(fake_image)
