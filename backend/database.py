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
        agent           TEXT NOT NULL,
        intent_confidence REAL NOT NULL DEFAULT 0,
        query           TEXT NOT NULL,
        response        TEXT NOT NULL,
        metadata_json   TEXT,
        citations_json  TEXT,
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


async def _migrate_messages_citations(conn: aiosqlite.Connection) -> None:
    """Idempotent: add `messages.citations_json` if upgrading from a pre-Phase-2 DB."""
    async with conn.execute("PRAGMA table_info(messages)") as cursor:
        existing_cols = {row[1] for row in await cursor.fetchall()}
    if "citations_json" not in existing_cols:
        await conn.execute("ALTER TABLE messages ADD COLUMN citations_json TEXT")


async def init_db() -> None:
    """Create tables and indexes if they do not yet exist; run migrations."""
    async with get_connection() as conn:
        for statement in SCHEMA_STATEMENTS:
            await conn.execute(statement)
        await _migrate_messages_citations(conn)
        await conn.commit()


async def save_message(
    *,
    user_id: str | None,
    agent: str,
    intent_confidence: float,
    query: str,
    response: str,
    metadata: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> int:
    """Persist a message exchange and return the row id."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO messages
                (user_id, agent, intent_confidence, query, response,
                 metadata_json, citations_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                agent,
                intent_confidence,
                query,
                response,
                json.dumps(metadata) if metadata else None,
                json.dumps(citations) if citations else None,
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


async def list_recent_messages(
    limit: int = 50, *, user_id: str | None = None
) -> list[dict[str, Any]]:
    """Return recent message exchanges, newest first.

    If `user_id` is provided, scope the query to that user; otherwise
    return all users' messages (admin view).
    """
    async with get_connection() as conn:
        if user_id is not None:
            stmt = """
                SELECT id, user_id, agent, intent_confidence, query, response,
                       metadata_json, citations_json, created_at
                FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            """
            params: tuple[Any, ...] = (user_id, limit)
        else:
            stmt = """
                SELECT id, user_id, agent, intent_confidence, query, response,
                       metadata_json, citations_json, created_at
                FROM messages
                ORDER BY id DESC
                LIMIT ?
            """
            params = (limit,)
        async with conn.execute(stmt, params) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]
