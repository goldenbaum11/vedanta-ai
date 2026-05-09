"""LLM client tests.

Both backends share the same `LLMClient` protocol; these tests check
each backend's wire format using respx to mock the HTTP layer:

- OllamaClient: `/api/chat` non-streaming + newline-delimited JSON streaming.
- OpenAICompatibleClient: `/v1/chat/completions` non-streaming + SSE streaming,
  plus the `/v1/models` auto-detection used when `OPENAI_COMPATIBLE_MODEL` is empty.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.models.llm_client import (
    LLMUnavailableError,
    OllamaClient,
    OpenAICompatibleClient,
)


pytestmark = pytest.mark.usefixtures("isolated_env")


async def test_ollama_complete_happy_path() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        chat = router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"role": "assistant", "content": "hello"}}
            )
        )
        client = OllamaClient()
        text = await client.complete("sys", "hi")
    assert text == "hello"
    body = chat.calls[0].request.read().decode()
    assert "test-model" in body
    assert '"stream":false' in body or '"stream": false' in body


async def test_ollama_raises_on_http_error() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=httpx.ConnectError("nope"))
        client = OllamaClient()
        with pytest.raises(LLMUnavailableError):
            await client.complete("sys", "hi")


async def test_ollama_raises_on_empty_content() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": ""}})
        )
        client = OllamaClient()
        with pytest.raises(LLMUnavailableError):
            await client.complete("sys", "hi")


async def test_ollama_complete_stream_yields_token_deltas() -> None:
    body = (
        b'{"message":{"content":"hel"},"done":false}\n'
        b'{"message":{"content":"lo"},"done":false}\n'
        b'{"message":{"content":""},"done":true}\n'
    )
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/x-ndjson"},
            )
        )
        client = OllamaClient()
        deltas: list[str] = []
        async for delta in client.complete_stream("sys", "hi"):
            deltas.append(delta)
    assert "".join(deltas) == "hello"


async def test_ollama_is_available_true_on_200() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.get("/api/tags").mock(return_value=httpx.Response(200, json={}))
        client = OllamaClient()
        assert await client.is_available() is True


async def test_ollama_is_available_false_on_error() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.get("/api/tags").mock(side_effect=httpx.ConnectError("down"))
        client = OllamaClient()
        assert await client.is_available() is False


async def test_openai_compatible_resolves_model_when_default_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "")
    from backend import config

    config.get_settings.cache_clear()

    with respx.mock(base_url="http://openai.test/v1") as router:
        router.get("/models").mock(
            return_value=httpx.Response(
                200, json={"data": [{"id": "auto-detected-model"}]}
            )
        )
        chat = router.post("/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"content": "hi from lm studio"}}]},
            )
        )
        client = OpenAICompatibleClient()
        text = await client.complete("sys", "hello")

    assert text == "hi from lm studio"
    body = chat.calls[0].request.read().decode()
    assert "auto-detected-model" in body
    auth = chat.calls[0].request.headers.get("authorization")
    assert auth == "Bearer test-key"


async def test_openai_compatible_no_models_loaded_raises() -> None:
    with respx.mock(base_url="http://openai.test/v1") as router:
        router.get("/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = OpenAICompatibleClient(default_model="")
        with pytest.raises(LLMUnavailableError):
            await client.complete("sys", "hi")


async def test_openai_compatible_stream_yields_sse_deltas() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b'data: [DONE]\n\n'
    )
    with respx.mock(base_url="http://openai.test/v1") as router:
        router.get("/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "lm-studio-model"}]})
        )
        router.post("/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=body,
                headers={"content-type": "text/event-stream"},
            )
        )
        client = OpenAICompatibleClient(default_model="")
        deltas: list[str] = []
        async for delta in client.complete_stream("sys", "hi"):
            deltas.append(delta)
    assert "".join(deltas) == "hello"


async def test_openai_compatible_stream_handles_finish_reason() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"only"},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    )
    with respx.mock(base_url="http://openai.test/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(
                200, content=body, headers={"content-type": "text/event-stream"}
            )
        )
        client = OpenAICompatibleClient(default_model="my-model")
        deltas: list[str] = []
        async for delta in client.complete_stream("sys", "hi"):
            deltas.append(delta)
    assert "".join(deltas) == "only"
