"""Shared helpers for agent modules.

Keeps Phase 1 stubs uniform so Phase 2+ implementations only need to add
RAG retrieval + LLM calls without changing each agent's surface.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models.llm_client import LLMUnavailableError, get_llm_client
from ..schemas import AgentName, AgentResponse

logger = logging.getLogger(__name__)


async def respond_with_llm(
    *,
    agent: AgentName,
    system_prompt: str,
    query: str,
    context: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    escalate: bool = False,
    fallback_text: str | None = None,
) -> AgentResponse:
    """Call the local LLM with the agent's system prompt; degrade gracefully.

    If the LLM is unreachable we return a clearly-marked stub response so
    the rest of the pipeline (UI, audit log) still functions during dev.
    """
    metadata: dict[str, Any] = {"agent": agent, **(metadata_extra or {})}
    try:
        llm = get_llm_client()
        text = await llm.complete(system_prompt=system_prompt, user_message=query)
        metadata["model"] = llm.default_model
        return AgentResponse(
            agent=agent,
            text=text,
            citations=citations or [],
            metadata=metadata,
            escalate=escalate,
        )
    except LLMUnavailableError as exc:
        logger.warning("Agent %s falling back: %s", agent, exc)
        metadata["llm_available"] = False
        metadata["error"] = str(exc)
        return AgentResponse(
            agent=agent,
            text=fallback_text
            or (
                f"[{agent} stub] The local LLM is not reachable yet. "
                "Start Ollama (`ollama serve`) or load a model in LM Studio "
                "and ensure LLM_PROVIDER in .env matches."
            ),
            citations=citations or [],
            metadata=metadata,
            escalate=escalate,
        )
