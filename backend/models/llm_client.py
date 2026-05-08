"""Unified async LLM client.

Currently targets a local Ollama instance via the HTTP API. Designed so an
LM Studio (OpenAI-compatible) fallback can be added without changing the
public surface used by the rest of the codebase.

All LLM traffic in the system MUST go through this module per the
project's architecture rules (see `.cursorrules`).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """Raised when the local LLM cannot be reached or returns an error."""


class OllamaClient:
    """Thin async wrapper over the Ollama HTTP API.

    Uses `/api/chat` so we can pass system + user roles cleanly. The model
    can be overridden per call; otherwise the configured default is used.
    """

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._default_model = default_model or settings.ollama_default_model
        self._timeout = timeout_seconds or settings.ollama_timeout_seconds

    @property
    def default_model(self) -> str:
        return self._default_model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        """Run a single-turn chat completion and return the assistant text."""
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": temperature, **(extra_options or {})},
        }

        url = f"{self._base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed: %s", exc)
            raise LLMUnavailableError(
                f"Ollama at {self._base_url} is unreachable: {exc}"
            ) from exc

        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailableError("Ollama returned an empty response.")
        return content.strip()

    async def is_available(self) -> bool:
        """Lightweight reachability probe used by `/health`."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


_client: OllamaClient | None = None


def get_llm_client() -> OllamaClient:
    """Process-wide singleton accessor."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client
