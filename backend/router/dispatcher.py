"""Dispatcher: routes a classified query to the right agent module.

Per `.cursorrules`, agents NEVER call each other. The dispatcher is the
single chokepoint that knows the agent registry.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from ..agents import (
    communication,
    infosec_guardian,
    media_engine,
    sanskrit_grammar,
    survival_skills,
    vedic_scholar,
)
from ..schemas import AgentName, AgentResponse

logger = logging.getLogger(__name__)

AgentHandler = Callable[[str, dict[str, Any]], Awaitable[AgentResponse]]

AGENT_REGISTRY: dict[AgentName, AgentHandler] = {
    "vedic_scholar": vedic_scholar.handle,
    "sanskrit_grammar": sanskrit_grammar.handle,
    "communication": communication.handle,
    "infosec": infosec_guardian.handle,
    "survival": survival_skills.handle,
    "media": media_engine.handle,
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
