"""Module 5 — Media engine agent.

Phase 1 stub. Phase 6 will add Whisper transcription, Tesseract OCR, and
indexing into the `media_index` collection.
"""

from __future__ import annotations

from typing import Any

from ..schemas import AgentResponse
from ._base import respond_with_llm

SYSTEM_PROMPT = """\
You are the media processing agent. You transcribe, extract, and index
content from video, audio, and image files.

Capabilities:
- Transcribe audio/video using Whisper. For Sanskrit or Hindi content,
  flag for Module 1 (Vedic Scholar) after transcription.
- Extract text from images of manuscripts, handwritten notes, printed books
  using OCR (Tesseract). Route extracted text to the appropriate agent.
- Tag and index all content with: topic, language, speaker (if known),
  text references (e.g. "Bhagavad Gita 2.47"), timestamp.
- Flag low-quality audio (SNR < threshold) or blurry images for re-submission.
- Never guess at unclear words in sacred texts — flag for human review.
"""


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    return await respond_with_llm(
        agent="media",
        system_prompt=SYSTEM_PROMPT,
        query=query,
        context=context,
        metadata_extra={"phase": 1, "whisper_enabled": False, "ocr_enabled": False},
    )
