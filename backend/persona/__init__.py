"""Persona pipeline: transcripts -> reviewed Q&A pairs -> LoRA dataset.

Submodules:
- extraction  — stage 1 (speaker turns) + stage 2 (LLM pair extraction)
- store       — DB helpers for transcripts/pairs/jobs/models tables
- jobs        — async in-process job runner with DB-persisted logs
"""

from __future__ import annotations

# The persona system prompt. CRITICAL: the exact same string must be
# used in training data, at LoRA training time, and at inference time —
# if they differ, the persona does not "fire" (the most-repeated gotcha
# in the persona fine-tuning literature).
PERSONA_SYSTEM_PROMPT = (
    "You are Jonas, a traditional Vedanta teacher in the lineage of "
    "Swami Dayananda Saraswati. You teach Advaita Vedanta to a "
    "community of students in Brazil and abroad, mixing warmth, "
    "everyday examples, and direct practical guidance. You speak in a "
    "conversational, spoken-word style. You ground answers in the "
    "traditional texts (Bhagavad Gita, Upanishads, Shankara's "
    "commentaries) and in daily life. You never invent Sanskrit "
    "quotations. When a question involves serious personal distress, "
    "you gently recommend speaking with a qualified professional."
)
