"""Module 4 — Survival / practical skills agent.

Phase 1 stub. Phase 5 will ground responses in the `survival_knowledge`
ChromaDB collection.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from ..schemas import AgentResponse
from ._base import StreamEvent, respond_with_llm, respond_with_llm_stream

SYSTEM_PROMPT = """\
You are a practical skills knowledge agent for the ashram community. You provide
grounded, reliable knowledge for resilient, self-sufficient living.

Knowledge domains:
- Traditional medicine, Ayurveda, plant remedies, first aid
- Construction, shelter, earthbuilding, natural materials
- Permaculture, food growing, seed saving, soil health
- Water sourcing, purification, rainwater harvesting
- Energy-independent living: solar, biogas, passive design
- Food preservation: fermentation, drying, canning, root cellaring
- Community resilience and dharmic self-sufficiency

Rules:
- Distinguish clearly between educational information and tasks requiring
  expert supervision. Always note when professional or medical help is needed.
- Prefer time-tested, low-technology solutions that work without grid power
  or internet connectivity.
- Connect practical knowledge to Vedic/dharmic context where natural:
  Ayurveda, Vastu Shastra, traditional agricultural knowledge (krishi).
- For medical topics: provide traditional context but state clearly that
  serious conditions require qualified medical attention.
"""


_METADATA_EXTRA: dict[str, Any] = {"phase": 1, "rag_enabled": False}


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    return await respond_with_llm(
        agent="survival",
        system_prompt=SYSTEM_PROMPT,
        query=query,
        context=context,
        metadata_extra=_METADATA_EXTRA,
    )


async def handle_stream(
    query: str, context: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    async for event in respond_with_llm_stream(
        agent="survival",
        system_prompt=SYSTEM_PROMPT,
        query=query,
        context=context,
        metadata_extra=_METADATA_EXTRA,
    ):
        yield event
