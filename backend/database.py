"""Async SQLite layer.

Creates the schema on startup and exposes small typed helpers used by the
rest of the backend. We use plural snake_case table names per the project
naming convention (see `.cursorrules`).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from .config import get_settings

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email       TEXT UNIQUE,
        role        TEXT NOT NULL DEFAULT 'student',
        password_hash TEXT,
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         TEXT,
        thread_id       TEXT,
        agent           TEXT NOT NULL,
        intent_confidence REAL NOT NULL DEFAULT 0,
        query           TEXT NOT NULL,
        response        TEXT NOT NULL,
        metadata_json   TEXT,
        citations_json  TEXT,
        escalate        INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT,
        endpoint    TEXT NOT NULL,
        method      TEXT NOT NULL,
        ip_address  TEXT,
        status_code INTEGER,
        detail      TEXT,
        created_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent)",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at)",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    path = get_settings().sqlite_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@asynccontextmanager
async def get_connection() -> AsyncIterator[aiosqlite.Connection]:
    """Yield an async SQLite connection with row factory set."""
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn


async def _existing_message_columns(conn: aiosqlite.Connection) -> set[str]:
    async with conn.execute("PRAGMA table_info(messages)") as cursor:
        return {row[1] for row in await cursor.fetchall()}


async def _migrate_messages(conn: aiosqlite.Connection) -> None:
    """Idempotent migrations adding columns introduced after Phase 1.

    `citations_json` (Phase 2) and `thread_id` + `escalate` (Phase 3)
    are added one at a time so existing dev databases keep their
    history.
    """
    cols = await _existing_message_columns(conn)
    if "citations_json" not in cols:
        await conn.execute("ALTER TABLE messages ADD COLUMN citations_json TEXT")
    if "thread_id" not in cols:
        await conn.execute("ALTER TABLE messages ADD COLUMN thread_id TEXT")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id)"
        )
    if "escalate" not in cols:
        await conn.execute(
            "ALTER TABLE messages ADD COLUMN escalate INTEGER NOT NULL DEFAULT 0"
        )


async def init_db() -> None:
    """Create tables and indexes if they do not yet exist; run migrations.

    Migrations run BEFORE the index/schema statements so the
    ``CREATE INDEX … ON messages(thread_id)`` step doesn't blow up
    when upgrading a pre-Phase-3 database (where `thread_id` doesn't
    yet exist on the messages table).
    """
    async with get_connection() as conn:
        # First make sure the canonical tables exist with at least
        # their original columns (this is a no-op for fresh DBs and
        # leaves legacy tables untouched).
        await conn.execute(SCHEMA_STATEMENTS[0])  # users
        await _ensure_messages_table(conn)
        await conn.execute(SCHEMA_STATEMENTS[2])  # audit_logs
        await _migrate_messages(conn)
        # Now that columns are guaranteed, lay down indexes.
        for statement in SCHEMA_STATEMENTS:
            if statement.lstrip().upper().startswith("CREATE INDEX"):
                await conn.execute(statement)
        await conn.commit()


async def _ensure_messages_table(conn: aiosqlite.Connection) -> None:
    """Create the messages table only if it does not exist.

    Using the full SCHEMA_STATEMENTS[1] is a no-op when the table
    already exists, so this is identical for fresh DBs. The reason
    we factor it out is purely so we can interleave migrations
    correctly.
    """
    await conn.execute(SCHEMA_STATEMENTS[1])


async def save_message(
    *,
    user_id: str | None,
    agent: str,
    intent_confidence: float,
    query: str,
    response: str,
    metadata: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    thread_id: str | None = None,
    escalate: bool = False,
) -> int:
    """Persist a message exchange and return the row id."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO messages
                (user_id, thread_id, agent, intent_confidence, query, response,
                 metadata_json, citations_json, escalate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                thread_id,
                agent,
                intent_confidence,
                query,
                response,
                json.dumps(metadata) if metadata else None,
                json.dumps(citations) if citations else None,
                1 if escalate else 0,
                _utcnow_iso(),
            ),
        )
        await conn.commit()
        return cursor.lastrowid or 0


async def write_audit_log(
    *,
    user_id: str | None,
    endpoint: str,
    method: str,
    ip_address: str | None = None,
    status_code: int | None = None,
    detail: str | None = None,
) -> None:
    """Append an immutable-by-convention audit row."""
    async with get_connection() as conn:
        await conn.execute(
            """
            INSERT INTO audit_logs
                (user_id, endpoint, method, ip_address, status_code,
                 detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, endpoint, method, ip_address, status_code, detail, _utcnow_iso()),
        )
        await conn.commit()


_MESSAGE_COLUMNS = (
    "id, user_id, thread_id, agent, intent_confidence, query, response, "
    "metadata_json, citations_json, escalate, created_at"
)


async def list_recent_messages(
    limit: int = 50,
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent message exchanges, newest first.

    Scopes:
    - `user_id` only: this user's full history across all threads.
    - `thread_id` only: every message in that thread (admin view).
    - both: this user's messages within that thread.
    - neither: full firehose (admin view).
    """
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if thread_id is not None:
        clauses.append("thread_id = ?")
        params.append(thread_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    stmt = (
        f"SELECT {_MESSAGE_COLUMNS} "
        f"FROM messages {where} ORDER BY id DESC LIMIT ?"
    )
    params.append(limit)
    async with get_connection() as conn:
        async with conn.execute(stmt, tuple(params)) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def list_threads(
    *, user_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Return thread summaries newest-first.

    Each row carries the thread id, the first message text (used as a
    title in the UI), the last activity timestamp, message count, and
    the most recent agent that handled the thread.
    """
    where = "WHERE thread_id IS NOT NULL"
    params: list[Any] = []
    if user_id is not None:
        where += " AND user_id = ?"
        params.append(user_id)
    # Subquery picks the first (oldest) query in each thread for the title.
    stmt = f"""
        SELECT
            thread_id,
            (SELECT query FROM messages m2
             WHERE m2.thread_id = messages.thread_id
             ORDER BY m2.id ASC LIMIT 1) AS title,
            COUNT(*) AS message_count,
            MAX(created_at) AS last_active_at,
            MIN(created_at) AS started_at,
            (SELECT agent FROM messages m3
             WHERE m3.thread_id = messages.thread_id
             ORDER BY m3.id DESC LIMIT 1) AS last_agent
        FROM messages
        {where}
        GROUP BY thread_id
        ORDER BY last_active_at DESC
        LIMIT ?
    """
    params.append(limit)
    async with get_connection() as conn:
        async with conn.execute(stmt, tuple(params)) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def load_thread_history(
    thread_id: str,
    *,
    user_id: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return the most recent N exchanges in chronological (oldest-first) order.

    The agent uses this to feed prior turns back into the LLM as
    context. We cap at `limit` exchanges so a long thread doesn't
    blow the context window — six round trips (twelve messages) is
    plenty for short-term grounding without overwhelming smaller
    local models.
    """
    rows = await list_recent_messages(
        limit=limit, user_id=user_id, thread_id=thread_id
    )
    return list(reversed(rows))
