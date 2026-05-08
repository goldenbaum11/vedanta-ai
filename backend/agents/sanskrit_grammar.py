"""Module 1b — Sanskrit Grammar agent.

Phase 1 stub. Phase 2 will integrate SanskritNLP / Sanskrit Heritage
Platform for structural parsing in addition to the LLM commentary.
"""

from __future__ import annotations

from typing import Any

from ..schemas import AgentResponse
from ._base import respond_with_llm

SYSTEM_PROMPT = """\
You are a Sanskrit grammar analysis agent.

Your responsibilities:
- Parse Sanskrit verses: identify sandhi (phonetic junctions), samasa (compound
  words), vibhakti (case endings), dhatu (verb roots), pratyaya (suffixes),
  and chandas (meter).
- Produce a structured grammatical breakdown of each word in a verse.
- Explain grammatical rules in accessible language for students learning Sanskrit.
- Use standard Devanagari notation and IAST transliteration side-by-side.
- Reference Panini's Ashtadhyayi rules when relevant (cite the sutra number).
"""


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    return await respond_with_llm(
        agent="sanskrit_grammar",
        system_prompt=SYSTEM_PROMPT,
        query=query,
        context=context,
        metadata_extra={"phase": 1, "structural_parser": "pending"},
    )
