"""Dispatcher: routes a classified query to the right agent module.

Per `.cursorrules`, agents NEVER call each other. The dispatcher is the
single chokepoint that knows the agent registry. It exposes both a
non-streaming `dispatch()` (returns one `AgentResponse`) and a
streaming `dispatch_stream()` (yields events for SSE/ndjson clients).
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Awaitable, Callable

from ..agents import (
    communication,
    infosec_guardian,
    media_engine,
    sanskrit_grammar,
    survival_skills,
    vedic_scholar,
)
from ..agents._base import StreamEvent
from ..schemas import AgentName, AgentResponse

logger = logging.getLogger(__name__)

AgentHandler = Callable[[str, dict[str, Any]], Awaitable[AgentResponse]]
AgentStreamHandler = Callable[
    [str, dict[str, Any]], AsyncIterator[StreamEvent]
]

AGENT_REGISTRY: dict[AgentName, AgentHandler] = {
    "vedic_scholar": vedic_scholar.handle,
    "sanskrit_grammar": sanskrit_grammar.handle,
    "communication": communication.handle,
    "infosec": infosec_guardian.handle,
    "survival": survival_skills.handle,
    "media": media_engine.handle,
}

AGENT_STREAM_REGISTRY: dict[AgentName, AgentStreamHandler] = {
    "vedic_scholar": vedic_scholar.handle_stream,
    "sanskrit_grammar": sanskrit_grammar.handle_stream,
    "communication": communication.handle_stream,
    "infosec": infosec_guardian.handle_stream,
    "survival": survival_skills.handle_stream,
    "media": media_engine.handle_stream,
}


async def dispatch(
    *,
    agent: AgentName,
    query: str,
    context: dict[str, Any] | None = None,
) -> AgentResponse:
    """Invoke the named agent and return its response envelope."""
    handler = AGENT_REGISTRY.get(agent)
    if handler is None:
        raise ValueError(f"Unknown agent: {agent}")
    logger.info("Dispatching to agent=%s", agent)
    return await handler(query, context or {})


async def dispatch_stream(
    *,
    agent: AgentName,
    query: str,
    context: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream events from the named agent.

    See `backend/agents/_base.py` for the event protocol (meta → tokens
    → done|error).
    """
    handler = AGENT_STREAM_REGISTRY.get(agent)
    if handler is None:
        raise ValueError(f"Unknown agent: {agent}")
    logger.info("Stream-dispatching to agent=%s", agent)
    async for event in handler(query, context or {}):
        yield event
