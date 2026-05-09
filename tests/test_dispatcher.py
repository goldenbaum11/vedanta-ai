"""Dispatcher tests.

End-to-end through the agent layer with the LLM mocked. Verifies:

- `dispatch()` routes by `AgentName` and returns a populated
  `AgentResponse` with the expected metadata shape.
- `dispatch_stream()` emits the documented event protocol
  (`meta` → `token`+ → `done`) and forwards token deltas verbatim.
- Unknown agent names raise `ValueError` (defensive — schemas should
  prevent this in practice).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.router import dispatcher


pytestmark = pytest.mark.usefixtures("isolated_env")


async def test_dispatch_routes_to_communication_agent() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "Hi from agent."}}
            )
        )
        response = await dispatcher.dispatch(
            agent="communication", query="hello", context={}
        )
    assert response.agent == "communication"
    assert response.text == "Hi from agent."
    assert response.metadata["agent"] == "communication"
    assert response.metadata["model"] == "test-model"


async def test_dispatch_routes_to_infosec_agent() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "all clear"}}
            )
        )
        response = await dispatcher.dispatch(
            agent="infosec", query="audit", context={}
        )
    assert response.agent == "infosec"
    assert response.text == "all clear"


async def test_dispatch_unknown_agent_raises() -> None:
    with pytest.raises(ValueError):
        await dispatcher.dispatch(agent="ghost", query="hi", context={})  # type: ignore[arg-type]


async def test_dispatch_stream_emits_protocol_events() -> None:
    body = (
        b'{"message":{"content":"Hi "},"done":false}\n'
        b'{"message":{"content":"there"},"done":false}\n'
        b'{"message":{"content":""},"done":true}\n'
    )
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, content=body, headers={"content-type": "application/x-ndjson"}
            )
        )
        events: list[dict] = []
        async for event in dispatcher.dispatch_stream(
            agent="communication", query="hi", context={}
        ):
            events.append(event)

    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert types[-1] == "done"
    tokens = [e["delta"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "Hi there"
    assert events[-1]["text"] == "Hi there"
    assert events[0]["agent"] == "communication"


async def test_dispatch_stream_unknown_agent_raises() -> None:
    with pytest.raises(ValueError):
        async for _ in dispatcher.dispatch_stream(
            agent="ghost",  # type: ignore[arg-type]
            query="hi",
            context={},
        ):
            pass


async def test_dispatch_stream_error_event_on_llm_failure() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=httpx.ConnectError("down"))
        events = [
            ev
            async for ev in dispatcher.dispatch_stream(
                agent="communication", query="hi", context={}
            )
        ]
    types = [e["type"] for e in events]
    assert "meta" in types
    assert types[-1] == "error"
    assert "text" in events[-1]
