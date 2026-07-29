"""Tests for the media agent's RAG + LLM logic (Phase 6).

Mirrors `test_communication_agent.py`'s structure: exercise the agent
through its public `handle`/`handle_stream` entry points, seed the
`media_index` collection via the in-memory chroma fixture, and mock the
LLM with respx. `transcribe.is_available`/`ocr.is_available` are
monkeypatched so metadata assertions don't depend on whether the real
(heavy, optional) whisper/pytesseract packages happen to be installed
in the environment running the suite.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.agents import media_engine
from backend.rag import vector_store

pytestmark = pytest.mark.usefixtures("isolated_env", "in_memory_chroma")


def _seed_media_index() -> None:
    vector_store.add_documents(
        collection_name="media_index",
        ids=["satsang1:0.0-45.0", "manuscript1:ocr0"],
        documents=[
            "[satsang1 0.0-45.0s]\nToday we discuss the meaning of karma yoga "
            "and selfless action in daily life.",
            "[manuscript1]\nA scanned page describing the ashram's founding in 1974.",
        ],
        metadatas=[
            {
                "source": "satsang1",
                "start": 0.0,
                "end": 45.0,
                "format": "media_transcript",
                "language": "en",
            },
            {"source": "manuscript1", "format": "media_ocr"},
        ],
    )


async def test_handle_runs_rag_then_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media_engine.transcribe, "is_available", lambda: False)
    monkeypatch.setattr(media_engine.ocr, "is_available", lambda: False)
    _seed_media_index()

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={"message": {"content": "The recording discusses karma yoga. [1]"}},
        )

    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=handler)
        result = await media_engine.handle("What did the satsang say about karma yoga?", context={})

    assert result.agent == "media"
    assert result.metadata["rag_enabled"] is True
    assert result.metadata["corpus"] == "media_index"
    assert result.metadata["hits"] >= 1
    assert "karma yoga" in result.text.lower()

    assert captured, "LLM was not called"
    user_msg = captured[0]["messages"][-1]["content"]
    assert "Indexed media excerpts" in user_msg
    assert "satsang1" in user_msg


async def test_handle_reports_whisper_and_ocr_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_engine.transcribe, "is_available", lambda: True)
    monkeypatch.setattr(media_engine.ocr, "is_available", lambda: False)

    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": "ok"}})
        )
        result = await media_engine.handle("Any transcripts about fasting?", context={})

    assert result.metadata["whisper_enabled"] is True
    assert result.metadata["ocr_enabled"] is False


async def test_handle_says_so_when_no_media_indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty media_index should not fabricate citations, but the LLM still runs."""
    monkeypatch.setattr(media_engine.transcribe, "is_available", lambda: False)
    monkeypatch.setattr(media_engine.ocr, "is_available", lambda: False)
    # chromadb's EphemeralClient can share underlying system state across
    # instances with identical settings, so other tests' seeded docs can
    # otherwise bleed through — reset explicitly rather than assume empty.
    vector_store.reset_collection("media_index")

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={"message": {"content": "Nothing in the library covers that yet."}},
        )

    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(side_effect=handler)
        result = await media_engine.handle("What did the 1999 retreat cover?", context={})

    assert result.metadata["hits"] == 0
    assert result.citations == []
    user_msg = captured[0]["messages"][-1]["content"]
    assert "No matching content found" in user_msg


async def test_handle_stream_yields_meta_then_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media_engine.transcribe, "is_available", lambda: False)
    monkeypatch.setattr(media_engine.ocr, "is_available", lambda: False)
    _seed_media_index()

    body = (
        b'{"message":{"content":"Karma "},"done":false}\n'
        b'{"message":{"content":"yoga."},"done":false}\n'
        b'{"message":{"content":""},"done":true}\n'
    )
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, content=body, headers={"content-type": "application/x-ndjson"}
            )
        )
        events = [
            event
            async for event in media_engine.handle_stream(
                "What did the satsang say?", context={}
            )
        ]

    types = [e["type"] for e in events]
    assert types == ["meta", "token", "token", "done"]
    assert events[0]["metadata"]["corpus"] == "media_index"
    assert events[-1]["text"] == "Karma yoga."
