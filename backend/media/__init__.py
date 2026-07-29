"""Media processing: Whisper transcription + Tesseract OCR (Phase 6).

Both backends are optional, heavy dependencies (see
`backend/requirements.txt`) that are lazily imported so the rest of the
app runs fine without them installed — the media agent and `/health`
just report the capability as unavailable. See `transcribe.py` and
`ocr.py`.
"""

from __future__ import annotations
