"""Intent classifier tests.

Covers the offline keyword path (no LLM call) and the LLM-fallback path
(mocked via respx). Ensures Devanagari shortcuts and graceful degradation
to "communication" both behave as the spec requires.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.router import intent_classifier
from backend.schemas import AGENT_NAMES


pytestmark = pytest.mark.usefixtures("isolated_env")


@pytest.mark.parametrize(
    ("message", "expected_agent"),
    [
        ("Translate Bhagavad Gita 2.47 with Shankara commentary", "vedic_scholar"),
        ("Parse the sandhi in this Sanskrit verse", "sanskrit_grammar"),
        ("Schedule an appointment for an ashram visit", "communication"),
        ("We had a security breach, please review the access log", "infosec"),
        ("How do I set up rainwater harvesting and biogas?", "survival"),
        ("Transcribe this Whisper audio file with subtitles", "media"),
    ],
)
async def test_keyword_paths_dominate(message: str, expected_agent: str) -> None:
    """Two or more keyword hits should win without ever touching the LLM."""
    with respx.mock(assert_all_called=False) as router:
        called = router.post("/api/chat")
        result = await intent_classifier.classify(message)
    assert result.agent == expected_agent
    assert result.confidence >= 0.6
    assert result.rationale == "keyword match"
    assert called.call_count == 0


async def test_devanagari_routes_to_vedic_scholar() -> None:
    result = await intent_classifier.classify("कृपया अनुवाद करें")
    assert result.agent == "vedic_scholar"


async def test_low_signal_falls_back_to_llm_label() -> None:
    """One faint keyword (or none) should trigger the LLM call and accept its label."""
    with respx.mock(base_url="http://ollama.test", assert_all_called=True) as router:
        chat = router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "survival"}}
            )
        )
        result = await intent_classifier.classify("hello there")
    assert result.agent == "survival"
    assert result.rationale == "llm_classifier"
    assert chat.call_count == 1


async def test_llm_garbage_response_falls_back_to_keyword_winner() -> None:
    """Non-canonical LLM output should not break us — degrade to keyword match or 'communication'."""
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "definitely not a label"}}
            )
        )
        result = await intent_classifier.classify("tell me a story")
    assert result.agent == "communication"
    assert result.rationale and result.rationale.startswith("llm_invalid:")


async def test_llm_unavailable_falls_back_quietly() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=httpx.ConnectError("nope"))
        result = await intent_classifier.classify("wat")
    assert result.agent == "communication"
    assert result.rationale == "llm_unavailable_keyword_fallback"
    assert result.confidence == pytest.approx(0.2)


def test_supported_agents_matches_schema() -> None:
    assert tuple(intent_classifier.supported_agents()) == AGENT_NAMES
