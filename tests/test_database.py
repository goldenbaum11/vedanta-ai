"""SQLite database tests.

Uses the per-test SQLite path provided by `isolated_env` so each test
runs against a fresh schema. Verifies:

- `init_db` is idempotent and creates the expected tables.
- `save_message` round-trips both metadata and the new
  `citations_json` column.
- The `_migrate_messages_citations` migration is idempotent and adds
  the column to a pre-Phase-2 schema.
- `list_recent_messages` honours `user_id` scoping.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest

from backend import database


pytestmark = pytest.mark.usefixtures("isolated_env")


async def test_init_db_creates_tables_and_is_idempotent() -> None:
    await database.init_db()
    await database.init_db()  # second call must not raise

    async with database.get_connection() as conn:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cur:
            tables = {row[0] for row in await cur.fetchall()}
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
    """Simulate a pre-Phase-2 DB (no `citations_json`) and verify
    `init_db` migrates it without dropping data."""
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

    await database.init_db()

    async with database.get_connection() as conn:
        async with conn.execute("PRAGMA table_info(messages)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
    assert "citations_json" in cols

    rows = await database.list_recent_messages()
    assert len(rows) == 1
    legacy_row = rows[0]
    assert legacy_row["user_id"] == "legacy"
    assert legacy_row["citations_json"] is None


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
        async with conn.execute(
            "SELECT user_id, endpoint, method, ip_address, status_code, detail FROM audit_logs"
        ) as cur:
            rows = await cur.fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["user_id"] == "alice"
    assert row["endpoint"] == "/api/v1/chat"
    assert row["status_code"] == 200
