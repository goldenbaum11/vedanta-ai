"""Shared helpers for agent modules.

Keeps agent boilerplate uniform: every agent calls one of two helpers
here for the LLM round trip, and the helpers handle audit-friendly
metadata, graceful degradation when the LLM is offline, and (for
streaming) the event protocol consumed by `/api/v1/chat/stream`.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ..models.llm_client import LLMUnavailableError, get_llm_client
from ..schemas import AgentName, AgentResponse

logger = logging.getLogger(__name__)

#: Stream events emitted by `respond_with_llm_stream`. Discriminated by
#: the `type` field; consumed by `dispatcher.dispatch_stream` and
#: serialized as ndjson by the API layer.
StreamEvent = dict[str, Any]


def _fallback_text(agent: AgentName) -> str:
    return (
        f"[{agent} stub] The local LLM is not reachable yet. "
        "Start Ollama (`ollama serve`) or load a model in LM Studio "
        "and ensure LLM_PROVIDER in .env matches."
    )


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
            text=fallback_text or _fallback_text(agent),
            citations=citations or [],
            metadata=metadata,
            escalate=escalate,
        )


async def respond_with_llm_stream(
    *,
    agent: AgentName,
    system_prompt: str,
    query: str,
    context: dict[str, Any],
    citations: list[dict[str, Any]] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    escalate: bool = False,
    fallback_text: str | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream the LLM response as a sequence of events.

    Event protocol (emitted in order):

    - ``{"type": "meta", "agent", "citations", "escalate", "metadata"}``
      — sent immediately so the UI can render citations and the agent
      label before any LLM tokens arrive.
    - ``{"type": "token", "delta": "..."}`` — zero or more, one per
      streamed chunk.
    - ``{"type": "done", "text": "<full accumulated text>"}`` — terminal
      success event; carries the joined text so the caller can persist
      the final `AgentResponse` without re-accumulating.
    - ``{"type": "error", "message": "...", "text": "<fallback>"}`` —
      terminal failure event; `text` is the graceful-degradation
      fallback used in place of LLM output.
    """
    metadata: dict[str, Any] = {"agent": agent, **(metadata_extra or {})}
    citations_payload = citations or []

    try:
        llm = get_llm_client()
        metadata["model"] = llm.default_model
    except Exception as exc:  # noqa: BLE001 - configuration-level errors only
        logger.warning("Agent %s could not resolve LLM client: %s", agent, exc)
        text = fallback_text or _fallback_text(agent)
        yield {
            "type": "meta",
            "agent": agent,
            "citations": citations_payload,
            "escalate": escalate,
            "metadata": {**metadata, "llm_available": False, "error": str(exc)},
        }
        yield {"type": "error", "message": str(exc), "text": text}
        return

    yield {
        "type": "meta",
        "agent": agent,
        "citations": citations_payload,
        "escalate": escalate,
        "metadata": metadata,
    }

    accumulated: list[str] = []
    try:
        async for delta in llm.complete_stream(
            system_prompt=system_prompt, user_message=query
        ):
            accumulated.append(delta)
            yield {"type": "token", "delta": delta}
    except LLMUnavailableError as exc:
        logger.warning("Agent %s falling back during stream: %s", agent, exc)
        text = fallback_text or _fallback_text(agent)
        yield {"type": "error", "message": str(exc), "text": text}
        return

    full_text = "".join(accumulated).strip()
    if not full_text:
        text = fallback_text or _fallback_text(agent)
        yield {
            "type": "error",
            "message": "LLM returned empty content.",
            "text": text,
        }
        return
    yield {"type": "done", "text": full_text}
