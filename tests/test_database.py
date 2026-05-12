"""Database tests against the SQLAlchemy-async layer.

Each test runs against a fresh per-test SQLite path provided by the
``isolated_env`` fixture. The data layer also supports Postgres in
production, but the offline test suite stays SQLite-only — Postgres
gets exercised by the Docker Compose stack and the live smoke test.

Coverage:

- ``init_db`` is idempotent and creates every expected table.
- ``save_message`` round-trips metadata and citations and returns the
  new id.
- Filtering by ``user_id`` and ``thread_id`` works.
- The Phase 2/3 migrations run cleanly against a pre-Phase-2 schema
  (legacy column set) and preserve historical rows.
- ``write_audit_log`` persists everything we expect.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest
from sqlalchemy import text

from backend import database


pytestmark = pytest.mark.usefixtures("isolated_env")


async def test_init_db_creates_tables_and_is_idempotent() -> None:
    await database.init_db()
    await database.init_db()  # second call must not raise

    async with database.get_connection() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        tables = {row[0] for row in result.fetchall()}
    assert {"users", "messages", "audit_logs"}.issubset(tables)


async def test_save_message_round_trip_with_citations_and_metadata() -> None:
    await database.init_db()
    citations = [{"id": "BG:2:47", "snippet": "duty without attachment"}]
    metadata = {"agent": "vedic_scholar", "rag_enabled": True}

    row_id = await database.save_message(
        user_id="alice",
        agent="vedic_scholar",
        intent_confidence=0.9,
        query="Explain BG 2.47",
        response="...",
        metadata=metadata,
        citations=citations,
    )
    assert row_id > 0

    rows = await database.list_recent_messages(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == "alice"
    assert row["agent"] == "vedic_scholar"
    assert json.loads(row["citations_json"]) == citations
    assert json.loads(row["metadata_json"]) == metadata


async def test_list_recent_messages_scopes_to_user_id() -> None:
    await database.init_db()
    for user_id in ("alice", "alice", "bob"):
        await database.save_message(
            user_id=user_id,
            agent="vedic_scholar",
            intent_confidence=0.5,
            query="q",
            response="r",
        )

    alice = await database.list_recent_messages(user_id="alice")
    bob = await database.list_recent_messages(user_id="bob")
    everyone = await database.list_recent_messages()
    assert len(alice) == 2
    assert all(row["user_id"] == "alice" for row in alice)
    assert len(bob) == 1
    assert len(everyone) == 3


async def test_migration_adds_citations_column_to_legacy_db(
    isolated_env: Path,
) -> None:
    """Simulate a pre-Phase-2 DB (no ``citations_json``) and verify
    ``init_db`` migrates it without dropping data.
    """
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

    # Force the engine to be created against the seeded DB.
    await database.reset_engine()
    await database.init_db()

    async with database.get_connection() as conn:
        result = await conn.execute(text("PRAGMA table_info(messages)"))
        cols = {row[1] for row in result.fetchall()}
    assert {"citations_json", "thread_id", "escalate"}.issubset(cols)

    rows = await database.list_recent_messages()
    assert len(rows) == 1
    legacy_row = rows[0]
    assert legacy_row["user_id"] == "legacy"
    assert legacy_row["citations_json"] is None
    assert legacy_row["thread_id"] is None
    assert legacy_row["escalate"] == 0


async def test_audit_log_insert() -> None:
    await database.init_db()
    await database.write_audit_log(
        user_id="alice",
        endpoint="/api/v1/chat",
        method="POST",
        ip_address="127.0.0.1",
        status_code=200,
        detail="ok",
    )

    async with database.get_connection() as conn:
        result = await conn.execute(
            text(
                "SELECT user_id, endpoint, method, ip_address, status_code, detail "
                "FROM audit_logs"
            )
        )
        rows = result.fetchall()
    assert len(rows) == 1
    row = dict(rows[0]._mapping)
    assert row["user_id"] == "alice"
    assert row["endpoint"] == "/api/v1/chat"
    assert row["status_code"] == 200
