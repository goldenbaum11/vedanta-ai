"""Tests for the communication agent's escalation + RAG logic.

We exercise the agent in isolation via its public ``handle`` and
``handle_stream`` entry points. The communications corpus is
populated via the in-memory chroma fixture; the LLM is mocked with
respx so distress short-circuits never reach a real model.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.agents import communication
from backend.rag import vector_store


pytestmark = pytest.mark.usefixtures("isolated_env", "in_memory_chroma")


def _seed_faq() -> None:
    """Drop a few FAQ rows into the communications collection."""
    vector_store.add_documents(
        collection_name="communications",
        ids=["faq:visiting:1", "faq:donations:1"],
        documents=[
            (
                "Visitors are welcome daily 6 AM to 8 PM. Morning satsang at "
                "6:30 AM, evening arati at 6:30 PM. Photography permitted in "
                "gardens but not in the inner sanctum."
            ),
            (
                "The ashram is supported by voluntary contributions. Bank "
                "transfer or UPI to ashram@oksbi. We never solicit donations "
                "during classes."
            ),
        ],
        metadatas=[
            {
                "source": "Ashram FAQ",
                "chapter": "visiting",
                "verse": "1",
                "category": "logistical_admin",
            },
            {
                "source": "Ashram FAQ",
                "chapter": "donations",
                "verse": "1",
                "category": "donation_support",
            },
        ],
    )


# -- escalation classifier (pure-function tests) --------------------------


@pytest.mark.parametrize(
    ("message", "expected_reason", "expected_escalate"),
    [
        ("I want to die.", "distress", True),
        ("I am thinking of suicide.", "distress", True),
        ("I'm being harassed at work.", "distress", True),
        ("Should I divorce my husband?", "personal_guidance", True),
        ("Please initiate me with a personal mantra.", "personal_guidance", True),
        ("Can you diagnose my condition?", "professional_referral", True),
        ("What time is morning satsang?", None, False),
        ("How can I donate?", None, False),
    ],
)
def test_classify_escalation(
    message: str, expected_reason: str | None, expected_escalate: bool
) -> None:
    reason, escalate = communication._classify_escalation(message)
    assert reason == expected_reason
    assert escalate is expected_escalate


# -- distress short-circuits (no LLM call) --------------------------------


async def test_distress_short_circuits_without_llm() -> None:
    """Distress messages return the canned response and skip the LLM."""
    with respx.mock(base_url="http://ollama.test", assert_all_called=False) as router:
        chat_route = router.post("/api/chat")
        result = await communication.handle(
            "i can't take it anymore, I want to kill myself",
            context={},
        )
    assert chat_route.called is False
    assert result.escalate is True
    assert "teacher" in result.text.lower()
    assert "[classification: distress_flag]" in result.text
    assert result.metadata["short_circuit"] is True
    assert result.metadata["llm_invoked"] is False
    assert result.metadata["escalation_reason"] == "distress"


async def test_distress_stream_short_circuits_without_llm() -> None:
    with respx.mock(base_url="http://ollama.test", assert_all_called=False) as router:
        chat_route = router.post("/api/chat")
        events = [
            event
            async for event in communication.handle_stream(
                "I am thinking about suicide", context={}
            )
        ]
    assert chat_route.called is False
    types = [e["type"] for e in events]
    assert types == ["meta", "done"]
    meta_event = events[0]
    done_event = events[1]
    assert meta_event["escalate"] is True
    assert meta_event["metadata"]["short_circuit"] is True
    assert "teacher" in done_event["text"].lower()


# -- normal RAG path ------------------------------------------------------


async def test_normal_question_runs_rag_then_calls_llm() -> None:
    _seed_faq()

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode())
        captured.append(body)
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": (
                        "Visitors are welcome daily 6 AM to 8 PM. "
                        "Morning satsang is at 6:30 AM. [1]\n\n"
                        "[classification: logistical_admin]"
                    )
                }
            },
        )

    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=handler)
        result = await communication.handle(
            "When can I visit the ashram?", context={}
        )

    assert result.escalate is False
    assert result.metadata["rag_enabled"] is True
    assert result.metadata["hits"] >= 1  # FAQ retrieval succeeded
    assert "morning satsang" in result.text.lower()
    # The augmented user message should include the knowledge-base block.
    assert captured, "LLM was not called"
    user_msg = captured[0]["messages"][-1]["content"]
    assert "Ashram knowledge base" in user_msg
    assert "User message:" in user_msg


async def test_personal_guidance_escalates_but_calls_llm() -> None:
    """Personal guidance should escalate AND let the LLM compose a warm reply."""
    _seed_faq()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": (
                        "Thank you for writing. Personal guidance is "
                        "offered by senior teachers via "
                        "guidance@example-ashram.org.\n\n"
                        "[classification: personal_guidance]"
                    )
                }
            },
        )

    with respx.mock(base_url="http://ollama.test") as router:
        chat_route = router.post("/api/chat").mock(side_effect=handler)
        result = await communication.handle(
            "Please initiate me with a personal mantra.", context={}
        )

    assert chat_route.called is True
    assert result.escalate is True
    assert result.metadata["escalation_reason"] == "personal_guidance"
    assert "personal_guidance" in result.text or "guidance@" in result.text


async def test_handle_uses_history_from_context() -> None:
    """Multi-turn history should reach the LLM from the context dict."""
    _seed_faq()

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured_payloads.append(_json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={"message": {"content": "ok\n\n[classification: other]"}},
        )

    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=handler)
        await communication.handle(
            "And what about evenings?",
            context={
                "thread_history": [
                    {"role": "user", "content": "When can I visit?"},
                    {"role": "assistant", "content": "Daily 6 AM to 8 PM."},
                ]
            },
        )

    msgs = captured_payloads[0]["messages"]
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "When can I visit?"
    assert msgs[2]["content"] == "Daily 6 AM to 8 PM."
