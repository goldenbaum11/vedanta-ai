"""Shared pydantic models used across the API surface and internal modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "vedic_scholar",
    "sanskrit_grammar",
    "communication",
    "infosec",
    "survival",
    "media",
]

AGENT_NAMES: tuple[AgentName, ...] = (
    "vedic_scholar",
    "sanskrit_grammar",
    "communication",
    "infosec",
    "survival",
    "media",
)


class ChatRequest(BaseModel):
    """Inbound chat message from the UI or an integration."""

    message: str = Field(min_length=1, max_length=8000)
    user_id: str | None = Field(default=None, max_length=128)
    agent_override: AgentName | None = Field(
        default=None,
        description="If set, bypasses the intent classifier and routes directly.",
    )


class IntentResult(BaseModel):
    """Output of the intent classifier."""

    agent: AgentName
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = None


class AgentResponse(BaseModel):
    """Standard envelope returned by every agent's `handle()` function."""

    agent: AgentName
    text: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    escalate: bool = False


class ChatResponse(BaseModel):
    """Final response sent back to the UI."""

    agent: AgentName
    text: str
    intent_confidence: float
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    escalate: bool = False
    created_at: datetime
