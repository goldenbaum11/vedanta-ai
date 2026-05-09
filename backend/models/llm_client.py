"""Unified async LLM client.

Supports two providers behind the same `complete()` / `is_available()`
surface:

- **Ollama** (default) via `/api/chat`.
- **OpenAI-compatible** local servers (LM Studio, llama.cpp `--server`,
  vLLM, Jan, etc.) via `/v1/chat/completions`.

Selection is driven by the `LLM_PROVIDER` env var. All LLM traffic in
the system MUST go through this module per `.cursorrules`.

Both providers support a `/chat`-style messages array, so we expose a
single ``complete_messages``/``complete_messages_stream`` pair that
takes the canonical OpenAI-style list (``[{"role":..., "content":...}, ...]``).
The single-turn ``complete`` / ``complete_stream`` helpers are kept as
thin wrappers for callers that don't need history.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Protocol

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

ChatMessage = dict[str, str]


def _build_messages(
    system_prompt: str,
    user_message: str,
    history: list[ChatMessage] | None = None,
) -> list[ChatMessage]:
    """Compose a system + history + user message list.

    `history` is a sequence of ``{"role": "user"|"assistant", "content": "..."}``
    entries in chronological order. The system prompt always goes first.
    """
    messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
    if history:
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM cannot be reached or returns an error."""


class LLMClient(Protocol):
    """Minimal duck-type every concrete client must satisfy."""

    @property
    def default_model(self) -> str: ...

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str: ...

    def complete_stream(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]: ...

    async def complete_messages(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str: ...

    def complete_messages_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]: ...

    async def is_available(self) -> bool: ...


class OllamaClient:
    """Thin async wrapper over the Ollama HTTP API (`/api/chat`)."""

    provider: str = "ollama"

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

    @property
    def base_url(self) -> str:
        return self._base_url

    async def complete_messages(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": list(messages),
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

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        return await self.complete_messages(
            _build_messages(system_prompt, user_message),
            model=model,
            temperature=temperature,
            extra_options=extra_options,
        )

    async def complete_messages_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content deltas as the model produces them.

        Ollama streams newline-delimited JSON objects of the shape
        ``{"message": {"content": "..."}, "done": false}``; the final
        chunk has ``"done": true``.
        """
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": list(messages),
            "stream": True,
            "options": {"temperature": temperature, **(extra_options or {})},
        }
        url = f"{self._base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        delta = (chunk.get("message") or {}).get("content")
                        if isinstance(delta, str) and delta:
                            yield delta
                        if chunk.get("done"):
                            return
        except httpx.HTTPError as exc:
            logger.warning("Ollama streaming request failed: %s", exc)
            raise LLMUnavailableError(
                f"Ollama at {self._base_url} is unreachable: {exc}"
            ) from exc

    async def complete_stream(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        async for delta in self.complete_messages_stream(
            _build_messages(system_prompt, user_message),
            model=model,
            temperature=temperature,
            extra_options=extra_options,
        ):
            yield delta

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


class OpenAICompatibleClient:
    """Async client for any local OpenAI-compatible server.

    Tested targets:
      - LM Studio (`http://localhost:1234/v1`)
      - llama.cpp `--server` (`http://localhost:8080/v1`)
      - vLLM, Jan, and other OpenAI-shape servers

    `model` may be left empty in config; if so we look up the first
    model exposed by `GET /v1/models` and use that. This is the common
    pattern with LM Studio where the GUI loads exactly one model.
    """

    provider: str = "openai_compatible"

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.openai_compatible_base_url).rstrip("/")
        self._default_model = default_model if default_model is not None else settings.openai_compatible_model
        self._api_key = api_key or settings.openai_compatible_api_key
        self._timeout = timeout_seconds or settings.openai_compatible_timeout_seconds

    @property
    def default_model(self) -> str:
        return self._default_model or "(auto-detected)"

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _resolve_model(self, override: str | None) -> str:
        if override:
            return override
        if self._default_model:
            return self._default_model
        # Auto-detect the first loaded model.
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self._base_url}/models", headers=self._headers()
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"OpenAI-compatible server at {self._base_url} could not list models: {exc}"
            ) from exc

        items = data.get("data") or []
        if not items:
            raise LLMUnavailableError(
                f"No models loaded at {self._base_url}. "
                "Open LM Studio and load a model into its local server first."
            )
        first = items[0]
        model_id = first.get("id") if isinstance(first, dict) else None
        if not isinstance(model_id, str):
            raise LLMUnavailableError(
                f"OpenAI-compatible server returned an unexpected model list shape."
            )
        return model_id

    async def complete_messages(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        chosen_model = await self._resolve_model(model)
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": list(messages),
            "stream": False,
            "temperature": temperature,
            **(extra_options or {}),
        }
        url = f"{self._base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload, headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("OpenAI-compatible request failed: %s", exc)
            raise LLMUnavailableError(
                f"OpenAI-compatible server at {self._base_url} is unreachable: {exc}"
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMUnavailableError("OpenAI-compatible server returned no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailableError("OpenAI-compatible server returned empty content.")
        return content.strip()

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        return await self.complete_messages(
            _build_messages(system_prompt, user_message),
            model=model,
            temperature=temperature,
            extra_options=extra_options,
        )

    async def complete_messages_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content deltas via OpenAI-compatible SSE streaming.

        Wire format: ``data: {json}\\n\\n`` per chunk, terminated by
        ``data: [DONE]\\n\\n``. Each JSON chunk's
        ``choices[0].delta.content`` carries the next token(s).
        """
        chosen_model = await self._resolve_model(model)
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": list(messages),
            "stream": True,
            "temperature": temperature,
            **(extra_options or {}),
        }
        url = f"{self._base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=self._headers()
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[len("data:") :].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0].get("delta") or {}).get("content")
                        if isinstance(delta, str) and delta:
                            yield delta
                        if choices[0].get("finish_reason"):
                            return
        except httpx.HTTPError as exc:
            logger.warning("OpenAI-compatible streaming request failed: %s", exc)
            raise LLMUnavailableError(
                f"OpenAI-compatible server at {self._base_url} is unreachable: {exc}"
            ) from exc

    async def complete_stream(
        self,
        system_prompt: str,
        user_message: str,
        *,
        model: str | None = None,
        temperature: float = 0.2,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        async for delta in self.complete_messages_stream(
            _build_messages(system_prompt, user_message),
            model=model,
            temperature=temperature,
            extra_options=extra_options,
        ):
            yield delta

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self._base_url}/models", headers=self._headers()
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False


_client: LLMClient | None = None


def _build_client() -> LLMClient:
    provider = get_settings().llm_provider
    if provider == "openai_compatible":
        return OpenAICompatibleClient()
    return OllamaClient()


def get_llm_client() -> LLMClient:
    """Process-wide singleton accessor; switches on `LLM_PROVIDER`."""
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def reset_llm_client() -> None:
    """Drop the cached client. Useful in tests and after env changes."""
    global _client
    _client = None
