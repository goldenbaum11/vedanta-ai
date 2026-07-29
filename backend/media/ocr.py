"""Tesseract-based image OCR.

Lazily imports `pytesseract` + `Pillow`. Also requires the `tesseract-ocr`
system binary on `PATH` (not a pip package) — `is_available()` checks
both the Python imports and that the binary actually runs.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import get_settings

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "OCR requires pytesseract + Pillow (`pip install pytesseract pillow`) "
    "plus the tesseract-ocr system package (`apt install tesseract-ocr` "
    "on Ubuntu). See backend/requirements.txt (Phase 6 section)."
)


def is_available() -> bool:
    """Can we import pytesseract + Pillow, and does the tesseract binary run?"""
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    try:
        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 - missing/broken binary counts as unavailable
        return False
    return True


def _ocr_sync(path: Path) -> str:
    import pytesseract
    from PIL import Image

    settings = get_settings()
    with Image.open(path) as img:
        text = pytesseract.image_to_string(img, lang=settings.ocr_language)
    return text.strip()


async def ocr_image(path: Path) -> str:
    """Extract text from an image file.

    Raises `RuntimeError` if pytesseract/Pillow/the tesseract binary
    aren't available, `FileNotFoundError` if `path` doesn't exist.
    """
    if not is_available():
        raise RuntimeError(INSTALL_HINT)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    return await asyncio.to_thread(_ocr_sync, path)
