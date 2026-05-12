"""Multi-turn / threading tests.

End-to-end checks that:

- A first turn auto-creates a `thread_id` and the response carries it.
- Subsequent turns echo the same id and the agent receives prior
  exchanges as ``thread_history`` (verified by inspecting the payload
  the LLM mock received).
- ``GET /api/v1/threads`` lists threads newest-first with sensible
  titles, and ``GET /api/v1/messages?thread_id=...`` is correctly
  scoped.
- The legacy migration path adds ``thread_id`` and ``escalate``
  columns idempotently.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import aiosqlite
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from backend import database
from backend.main import create_app


pytestmark = pytest.mark.usefixtures("isolated_env")


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    if hasattr(app.state, "limiter"):
        app.state.limiter.reset()
    with TestClient(app) as test_client:
        yield test_client


def test_first_turn_creates_thread(client: TestClient) -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "first reply"}}
            )
        )
        response = client.post(
            "/api/v1/chat",
            json={"message": "hello", "agent_override": "communication"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["thread_id"], str)
    assert body["thread_id"].startswith("thread_")
    assert body["text"] == "first reply"


def test_second_turn_in_same_thread_replays_history(client: TestClient) -> None:
    """The second turn should send prior user+assistant messages to the LLM."""
    captured_payloads: list[dict] = []
    with respx.mock(base_url="http://ollama.test") as router:
        def handler(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content.decode()))
            reply = f"reply-{len(captured_payloads)}"
            return httpx.Response(200, json={"message": {"content": reply}})

        router.post("/api/chat").mock(side_effect=handler)

        first = client.post(
            "/api/v1/chat",
            json={"message": "What is dharma?", "agent_override": "communication"},
        )
        thread_id = first.json()["thread_id"]
        assert thread_id

        second = client.post(
            "/api/v1/chat",
            json={
                "message": "Give me an example.",
                "thread_id": thread_id,
                "agent_override": "communication",
            },
        )
    assert second.status_code == 200, second.text
    assert second.json()["thread_id"] == thread_id

    # First call should have system + user only; second should have
    # system + (user + assistant from turn 1) + user.
    assert len(captured_payloads) == 2
    first_msgs = captured_payloads[0]["messages"]
    second_msgs = captured_payloads[1]["messages"]
    assert [m["role"] for m in first_msgs] == ["system", "user"]
    assert [m["role"] for m in second_msgs] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    # Prior-turn content goes in verbatim. The communication agent
    # wraps the latest user message with its knowledge-base prefix,
    # so we just assert containment.
    assert second_msgs[1]["content"] == "What is dharma?"
    assert second_msgs[2]["content"] == "reply-1"
    assert "Give me an example." in second_msgs[3]["content"]


def test_threads_endpoint_lists_threads_newest_first(client: TestClient) -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "ok"}}
            )
        )
        first = client.post(
            "/api/v1/chat",
            json={"message": "first thread", "agent_override": "communication"},
        )
        second = client.post(
            "/api/v1/chat",
            json={"message": "second thread", "agent_override": "communication"},
        )

    threads = client.get("/api/v1/threads").json()["threads"]
    ids = [t["thread_id"] for t in threads]
    assert first.json()["thread_id"] in ids
    assert second.json()["thread_id"] in ids
    # Most recent thread first.
    assert threads[0]["thread_id"] == second.json()["thread_id"]
    assert threads[0]["title"] == "second thread"
    assert threads[0]["message_count"] == 1


def test_messages_filtered_by_thread_id(client: TestClient) -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200, json={"message": {"content": "ok"}}
            )
        )
        first = client.post(
            "/api/v1/chat",
            json={"message": "thread A turn 1", "agent_override": "communication"},
        )
        thread_a = first.json()["thread_id"]
        client.post(
            "/api/v1/chat",
            json={
                "message": "thread A turn 2",
                "thread_id": thread_a,
                "agent_override": "communication",
            },
        )
        client.post(
            "/api/v1/chat",
            json={"message": "thread B turn 1", "agent_override": "communication"},
        )

    scoped = client.get(f"/api/v1/messages?thread_id={thread_a}").json()["messages"]
    assert len(scoped) == 2
    queries = sorted(row["query"] for row in scoped)
    assert queries == ["thread A turn 1", "thread A turn 2"]
    assert all(row["thread_id"] == thread_a for row in scoped)


async def test_load_thread_history_returns_chronological() -> None:
    await database.init_db()
    thread = "thread_test"
    for i in range(3):
        await database.save_message(
            user_id="u1",
            thread_id=thread,
            agent="vedic_scholar",
            intent_confidence=1.0,
            query=f"q{i}",
            response=f"r{i}",
        )
    rows = await database.load_thread_history(thread, user_id="u1", limit=5)
    assert [row["query"] for row in rows] == ["q0", "q1", "q2"]


async def test_migration_adds_thread_id_and_escalate(
    isolated_env: Path,
) -> None:
    """Pre-Phase-3 schema (no thread_id, no escalate) should be migrated cleanly."""
    db_path = isolated_env / "test.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT,
                agent           TEXT NOT NULL,
                intent_confidence REAL NOT NULL DEFAULT 0,
                query           TEXT NOT NULL,
                response        TEXT NOT NULL,
                metadata_json   TEXT,
                created_at      TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            "INSERT INTO messages "
            "(user_id, agent, intent_confidence, query, response, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy", "vedic_scholar", 0.7, "old q", "old r", None, "2024-01-01T00:00:00"),
        )
        await conn.commit()

    # Force the engine onto the seeded DB.
    await database.reset_engine()
    await database.init_db()

    from sqlalchemy import text

    async with database.get_connection() as conn:
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        cols = {row[1] for row in result.fetchall()}
    assert {"thread_id", "escalate", "citations_json"}.issubset(cols)

    rows = await database.list_recent_messages()
    assert len(rows) == 1
    legacy = rows[0]
    assert legacy["thread_id"] is None
    assert legacy["escalate"] == 0
    assert legacy["query"] == "old q"
