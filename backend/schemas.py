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


class RegisterRequest(BaseModel):
    """Sign-up payload. Email is normalised to lower-case in the route."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    """Username/password sign-in."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """OAuth2-shaped token reply.

    `access_token` is the JWT itself; clients send it back via the
    `Authorization: Bearer <token>` header. `expires_in` is in seconds.
    `user` carries minimal profile info so the UI doesn't need a
    follow-up call.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: dict[str, Any]


class UserProfile(BaseModel):
    """Public user profile (no password hash)."""

    id: int
    email: str
    role: str
