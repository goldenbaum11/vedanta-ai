"""Whisper-based audio/video transcription.

Lazily imports `whisper` (the `openai-whisper` package) so the base
install stays slim — same precedent as `knowledge/chunker.chunk_pdf`'s
lazy `pypdf` import. Transcription is a blocking CPU/GPU call, so
`transcribe_file` runs it in a worker thread via `asyncio.to_thread`
rather than blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "Transcription requires openai-whisper (and ffmpeg on PATH). Install "
    "with `pip install openai-whisper` — see backend/requirements.txt "
    "(Phase 6 section)."
)


@dataclass(frozen=True)
class TranscriptSegment:
    """One timestamped Whisper segment."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    """Full transcription output for one media file."""

    text: str
    language: str
    segments: list[TranscriptSegment] = field(default_factory=list)


def is_available() -> bool:
    """Cheap check: can we import whisper? Does not load a model."""
    try:
        import whisper  # noqa: F401
    except ImportError:
        return False
    return True


_model: Any | None = None
_model_lock = threading.Lock()


def _get_model() -> Any:
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            try:
                import whisper
            except ImportError as exc:
                raise RuntimeError(INSTALL_HINT) from exc
            settings = get_settings()
            logger.info(
                "Loading Whisper model %r on %s (first call only, cached after)",
                settings.whisper_model_size,
                settings.whisper_device,
            )
            _model = whisper.load_model(
                settings.whisper_model_size, device=settings.whisper_device
            )
    return _model


def reset_model() -> None:
    """Drop the cached model. Tests call this between cases; also useful
    after changing `WHISPER_MODEL_SIZE`/`WHISPER_DEVICE` at runtime."""
    global _model
    _model = None


def _transcribe_sync(path: Path) -> TranscriptResult:
    model = _get_model()
    result = model.transcribe(str(path))
    segments = [
        TranscriptSegment(
            start=float(seg.get("start", 0.0)),
            end=float(seg.get("end", 0.0)),
            text=str(seg.get("text", "")).strip(),
        )
        for seg in result.get("segments", [])
    ]
    return TranscriptResult(
        text=str(result.get("text", "")).strip(),
        language=str(result.get("language", "")),
        segments=segments,
    )


async def transcribe_file(path: Path) -> TranscriptResult:
    """Transcribe an audio/video file.

    Raises `RuntimeError` if whisper isn't installed, `FileNotFoundError`
    if `path` doesn't exist. The model is loaded lazily on first call and
    cached for the life of the process.
    """
    if not is_available():
        raise RuntimeError(INSTALL_HINT)
    if not path.exists():
        raise FileNotFoundError(f"Media file not found: {path}")
    return await asyncio.to_thread(_transcribe_sync, path)
