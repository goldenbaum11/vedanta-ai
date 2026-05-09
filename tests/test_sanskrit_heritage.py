"""Tests for the Sanskrit Heritage Platform integration.

Covers both the low-level HTTP client and the agent-level
integration. The actual SHP server is never contacted — every
request goes through ``respx`` so the suite stays offline.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.agents import sanskrit_grammar
from backend.grammar import sanskrit_heritage
from backend.rag import vector_store


pytestmark = pytest.mark.usefixtures("isolated_env")


_SHP_HTML = """\
<html><body>
  <h2>Sanskrit Reader</h2>
  <p>Input: karmaṇyevādhikāraste mā phaleṣu kadācana</p>
  <ul>
    <li>karmaṇi = noun, locative singular of karman (action)</li>
    <li>eva = particle (only)</li>
    <li>adhikāraḥ = noun, nominative singular of adhikāra (right)</li>
    <li>te = pronoun, genitive of tva (your)</li>
    <li>mā = particle (do not)</li>
    <li>phaleṣu = noun, locative plural of phala (fruits)</li>
    <li>kadācana = adverb (ever)</li>
  </ul>
</body></html>"""


# -- Low-level client tests ------------------------------------------------


async def test_parser_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "false")
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()
    assert sanskrit_heritage.get_default_parser() is None


async def test_parser_enabled_calls_endpoint_and_strips_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "true")
    monkeypatch.setenv(
        "SANSKRIT_HERITAGE_BASE_URL", "http://shp.test/cgi-bin/SKT/sktreader.cgi"
    )
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()

    parser = sanskrit_heritage.get_default_parser()
    assert parser is not None

    with respx.mock(base_url="http://shp.test") as router:
        route = router.get("/cgi-bin/SKT/sktreader.cgi").mock(
            return_value=httpx.Response(200, text=_SHP_HTML)
        )
        result = await parser.analyze(
            "karmaṇyevādhikāraste mā phaleṣu kadācana"
        )

    assert route.called is True
    assert result.success is True
    assert result.parser == "sanskrit_heritage"
    # HTML should be stripped to readable text.
    assert "<html>" not in result.analysis
    assert "<li>" not in result.analysis
    assert "karman" in result.analysis
    assert "locative" in result.analysis
    # Should have hit the configured endpoint with sensible params.
    sent = route.calls.last.request
    assert "karma" in sent.url.params.get("text", "")
    assert sent.url.params.get("lex") == "SH"


async def test_parser_returns_failure_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "true")
    monkeypatch.setenv(
        "SANSKRIT_HERITAGE_BASE_URL", "http://shp.test/cgi-bin/SKT/sktreader.cgi"
    )
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()

    parser = sanskrit_heritage.get_default_parser()
    assert parser is not None

    with respx.mock(base_url="http://shp.test") as router:
        router.get("/cgi-bin/SKT/sktreader.cgi").mock(
            return_value=httpx.Response(500, text="boom")
        )
        result = await parser.analyze("karmaṇi")

    assert result.success is False
    assert result.error and "http error" in result.error
    assert result.analysis == ""


async def test_parser_returns_failure_on_empty_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "true")
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()
    parser = sanskrit_heritage.get_default_parser()
    assert parser is not None
    result = await parser.analyze("   ")
    assert result.success is False
    assert result.error == "empty input"


def test_devanagari_is_detected() -> None:
    assert sanskrit_heritage._is_devanagari("कर्म") is True
    assert sanskrit_heritage._is_devanagari("karma") is False


# -- Agent integration tests ----------------------------------------------


def _seed_gita() -> None:
    """Drop one Gita verse into vedic_texts so retrieval finds it."""
    vector_store.add_documents(
        collection_name="vedic_texts",
        ids=["bg:2:47"],
        documents=[
            "Bhagavad Gita 2.47\n"
            "कर्मण्येवाधिकारस्ते मा फलेषु कदाचन ।\n"
            "karmaṇyevādhikāraste mā phaleṣu kadācana .\n"
            "You have a right to action only, never to its fruits."
        ],
        metadatas=[
            {
                "source": "Bhagavad Gita",
                "chapter": "2",
                "verse": "47",
            }
        ],
    )


async def test_agent_skips_parser_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    in_memory_chroma: None,
) -> None:
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "false")
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()
    _seed_gita()

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content.decode()))
        return httpx.Response(
            200, json={"message": {"content": "analysis"}}
        )

    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=handler)
        result = await sanskrit_grammar.handle("Parse BG 2.47", context={})

    assert result.metadata["structural_parser"] == "disabled"
    assert result.metadata["structural_parser_used"] is False
    user_msg = captured[0]["messages"][-1]["content"]
    assert "Structural parser analysis" not in user_msg


async def test_agent_uses_parser_output_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    in_memory_chroma: None,
) -> None:
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "true")
    monkeypatch.setenv(
        "SANSKRIT_HERITAGE_BASE_URL", "http://shp.test/cgi-bin/SKT/sktreader.cgi"
    )
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()
    _seed_gita()

    captured: list[dict] = []

    def llm_handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content.decode()))
        return httpx.Response(
            200, json={"message": {"content": "analysis"}}
        )

    with respx.mock(assert_all_called=False) as router:
        shp_route = router.get(
            "http://shp.test/cgi-bin/SKT/sktreader.cgi"
        ).mock(return_value=httpx.Response(200, text=_SHP_HTML))
        router.post("http://ollama.test/api/chat").mock(side_effect=llm_handler)

        result = await sanskrit_grammar.handle("Parse BG 2.47", context={})

    assert shp_route.called is True
    assert result.metadata["structural_parser"] == "sanskrit_heritage"
    assert result.metadata["structural_parser_used"] is True
    user_msg = captured[0]["messages"][-1]["content"]
    assert "Structural parser analysis" in user_msg
    assert "locative" in user_msg.lower()


async def test_agent_continues_when_parser_fails(
    monkeypatch: pytest.MonkeyPatch,
    in_memory_chroma: None,
) -> None:
    """Parser HTTP failure must not break the agent."""
    monkeypatch.setenv("SANSKRIT_HERITAGE_ENABLED", "true")
    monkeypatch.setenv(
        "SANSKRIT_HERITAGE_BASE_URL", "http://shp.test/cgi-bin/SKT/sktreader.cgi"
    )
    sanskrit_heritage.reset_default_parser()
    from backend import config

    config.get_settings.cache_clear()
    _seed_gita()

    with respx.mock(assert_all_called=False) as router:
        router.get("http://shp.test/cgi-bin/SKT/sktreader.cgi").mock(
            return_value=httpx.Response(503, text="overloaded")
        )
        router.post("http://ollama.test/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "analysis"}}
            )
        )
        result = await sanskrit_grammar.handle("Parse BG 2.47", context={})

    # Parser failed → agent still answers, parser metadata records it.
    assert result.metadata["structural_parser"] == "sanskrit_heritage"
    assert result.metadata["structural_parser_used"] is False
    assert result.text == "analysis"
