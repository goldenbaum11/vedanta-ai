"""Async SQL data layer.

Backed by SQLAlchemy Core's async engine so the same code path works
against SQLite (dev) and PostgreSQL (Docker prod). The public surface
mirrors the original aiosqlite-only helpers — callers don't care
which driver is underneath.

Driver selection is automatic from ``DATABASE_URL``:

* ``sqlite:///./vedanta.db`` → ``sqlite+aiosqlite:///./vedanta.db``
* ``postgres://user:pass@host/db`` (or ``postgresql://``) → uses
  ``postgresql+asyncpg``.

Notes:

* All queries use named parameters (``:name``) so they translate
  cleanly across dialects.
* Auto-incrementing primary keys are declared via SQLAlchemy
  ``Integer + primary_key=True``, which is rendered as
  ``INTEGER PRIMARY KEY AUTOINCREMENT`` on SQLite and
  ``BIGSERIAL`` on Postgres.
* Inserts that need the new id ``RETURNING`` it explicitly so we
  don't depend on ``cursor.lastrowid`` (SQLite-only).
* The schema is created on startup; existing dev DBs are migrated
  in place by checking ``inspect()`` for missing columns.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .config import get_settings

logger = logging.getLogger(__name__)

# Re-export so callers (e.g. backend.security.auth) can catch the
# integrity error from a single neutral location instead of importing
# directly from sqlalchemy.
__all__ = [
    "IntegrityError",
    "get_connection",
    "get_engine",
    "init_db",
    "list_recent_messages",
    "list_threads",
    "load_thread_history",
    "reset_engine",
    "save_message",
    "write_audit_log",
]


# --- Schema ---------------------------------------------------------------

metadata = MetaData()

users_table = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(320), unique=True),
    Column("role", String(32), nullable=False, server_default=text("'student'")),
    Column("password_hash", String(255)),
    Column("created_at", String(64), nullable=False),
)

messages_table = Table(
    "messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(128)),
    Column("thread_id", String(64)),
    Column("agent", String(64), nullable=False),
    Column("intent_confidence", Float, nullable=False, server_default=text("0")),
    Column("query", Text, nullable=False),
    Column("response", Text, nullable=False),
    Column("metadata_json", Text),
    Column("citations_json", Text),
    Column("escalate", Integer, nullable=False, server_default=text("0")),
    Column("created_at", String(64), nullable=False),
    Index("idx_messages_user_id", "user_id"),
    Index("idx_messages_thread_id", "thread_id"),
    Index("idx_messages_agent", "agent"),
)

audit_logs_table = Table(
    "audit_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(128)),
    Column("endpoint", String(255), nullable=False),
    Column("method", String(16), nullable=False),
    Column("ip_address", String(64)),
    Column("status_code", Integer),
    Column("detail", Text),
    Column("created_at", String(64), nullable=False),
    Index("idx_audit_logs_user_id", "user_id"),
    Index("idx_audit_logs_created_at", "created_at"),
)


# --- Engine plumbing -----------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_database_url(raw: str) -> str:
    """Translate user-friendly URLs to async-driver URLs.

    * ``sqlite:///path``           → ``sqlite+aiosqlite:///path``
    * ``postgres://user@h/db``     → ``postgresql+asyncpg://user@h/db``
    * ``postgresql://user@h/db``   → ``postgresql+asyncpg://user@h/db``
    * URLs that already specify a driver are passed through untouched.
    """
    if not raw:
        raise ValueError("DATABASE_URL is empty")
    parsed = urlparse(raw)
    scheme = parsed.scheme
    if "+" in scheme:
        return raw  # caller knows what they're doing
    if scheme == "sqlite":
        return raw.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if scheme in {"postgres", "postgresql"}:
        # asyncpg is fussy about ssl=True flags in the query string;
        # we leave the rest of the URL alone.
        return raw.replace(f"{scheme}://", "postgresql+asyncpg://", 1)
    return raw


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a SQLite DB if it doesn't exist."""
    if not url.startswith("sqlite"):
        return
    parsed = urlparse(url)
    db_path = parsed.path.lstrip("/")
    if not db_path or db_path in (":memory:",):
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Return the process-global async engine, creating it on first call."""
    global _engine
    if _engine is None:
        url = _normalize_database_url(get_settings().database_url)
        _ensure_sqlite_dir(url)
        _engine = create_async_engine(
            url,
            future=True,
            pool_pre_ping=True,
            # SQLite needs ``check_same_thread=False`` for our async
            # use; SQLAlchemy + aiosqlite handles this correctly under
            # the default settings, no special connect_args needed.
        )
        logger.info("Database engine initialised: %s", _scrub(url))
    return _engine


def _scrub(url: str) -> str:
    """Hide credentials when logging a DB URL."""
    parsed = urlparse(url)
    if parsed.password:
        netloc = parsed.netloc.replace(parsed.password, "***")
        return parsed._replace(netloc=netloc).geturl()
    return url


async def reset_engine() -> None:
    """Dispose the current engine. Tests call this between cases."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def get_connection() -> AsyncIterator[AsyncConnection]:
    """Yield an async connection from the engine.

    Connections are checked out from the pool, autocommit is OFF (we
    explicitly ``commit()`` after each unit of work), and the
    underlying driver is whatever the URL selects.
    """
    engine = get_engine()
    async with engine.connect() as conn:
        yield conn


# --- Schema migration ----------------------------------------------------


async def _existing_columns(conn: AsyncConnection, table_name: str) -> set[str]:
    def _names(sync_conn: Any) -> set[str]:
        inspector = inspect(sync_conn)
        if not inspector.has_table(table_name):
            return set()
        return {col["name"] for col in inspector.get_columns(table_name)}

    return await conn.run_sync(_names)


_PHASE_2_3_MIGRATIONS: tuple[tuple[str, str], ...] = (
    # (column_name, ADD COLUMN sql tail)
    ("citations_json", "citations_json TEXT"),
    ("thread_id", "thread_id TEXT"),
    ("escalate", "escalate INTEGER NOT NULL DEFAULT 0"),
)


async def _migrate_messages(conn: AsyncConnection) -> None:
    """Idempotent ALTER TABLE migrations for legacy databases.

    Both SQLite and Postgres accept the same ``ALTER TABLE … ADD COLUMN``
    DDL, so we share one path.
    """
    cols = await _existing_columns(conn, "messages")
    if not cols:
        return  # fresh DB; create_all already covers everything
    for col_name, ddl in _PHASE_2_3_MIGRATIONS:
        if col_name not in cols:
            logger.info("Migrating messages: adding column %s", col_name)
            await conn.execute(text(f"ALTER TABLE messages ADD COLUMN {ddl}"))


async def init_db() -> None:
    """Create all tables/indexes if absent, then run column-level migrations."""
    engine = get_engine()
    async with engine.begin() as conn:
        # Create the canonical schema first. ``create_all`` is a no-op
        # for tables that already exist with the right columns.
        await conn.run_sync(metadata.create_all)
        await _migrate_messages(conn)


# --- Inserts -------------------------------------------------------------


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
    stmt = text(
        """
        INSERT INTO messages
            (user_id, thread_id, agent, intent_confidence, query, response,
             metadata_json, citations_json, escalate, created_at)
        VALUES
            (:user_id, :thread_id, :agent, :intent_confidence, :query, :response,
             :metadata_json, :citations_json, :escalate, :created_at)
        RETURNING id
        """
    )
    params = {
        "user_id": user_id,
        "thread_id": thread_id,
        "agent": agent,
        "intent_confidence": intent_confidence,
        "query": query,
        "response": response,
        "metadata_json": json.dumps(metadata) if metadata else None,
        "citations_json": json.dumps(citations) if citations else None,
        "escalate": 1 if escalate else 0,
        "created_at": _utcnow_iso(),
    }
    async with get_connection() as conn:
        result = await conn.execute(stmt, params)
        new_id = result.scalar_one()
        await conn.commit()
        return int(new_id or 0)


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
    stmt = text(
        """
        INSERT INTO audit_logs
            (user_id, endpoint, method, ip_address, status_code, detail, created_at)
        VALUES
            (:user_id, :endpoint, :method, :ip_address, :status_code, :detail, :created_at)
        """
    )
    async with get_connection() as conn:
        await conn.execute(
            stmt,
            {
                "user_id": user_id,
                "endpoint": endpoint,
                "method": method,
                "ip_address": ip_address,
                "status_code": status_code,
                "detail": detail,
                "created_at": _utcnow_iso(),
            },
        )
        await conn.commit()


# --- Reads ---------------------------------------------------------------


_MESSAGE_COLUMNS = (
    "id, user_id, thread_id, agent, intent_confidence, query, response, "
    "metadata_json, citations_json, escalate, created_at"
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    """SQLAlchemy ``Row`` → plain dict so callers don't depend on the type."""
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


async def list_recent_messages(
    limit: int = 50,
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent message exchanges, newest first.

    Scopes:
    - ``user_id`` only: this user's full history across all threads.
    - ``thread_id`` only: every message in that thread (admin view).
    - both: this user's messages within that thread.
    - neither: full firehose (admin view).
    """
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if user_id is not None:
        clauses.append("user_id = :user_id")
        params["user_id"] = user_id
    if thread_id is not None:
        clauses.append("thread_id = :thread_id")
        params["thread_id"] = thread_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    stmt = text(
        f"SELECT {_MESSAGE_COLUMNS} "
        f"FROM messages {where} ORDER BY id DESC LIMIT :limit"
    )
    async with get_connection() as conn:
        result = await conn.execute(stmt, params)
        rows = result.fetchall()
    return [_row_to_dict(r) for r in rows]


async def list_threads(
    *, user_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Return thread summaries newest-first.

    Each row carries the thread id, the first message text (used as a
    title in the UI), the last activity timestamp, message count, and
    the most recent agent that handled the thread.

    The correlated subqueries that pick title/last_agent work
    identically on SQLite and Postgres.
    """
    where = "WHERE thread_id IS NOT NULL"
    params: dict[str, Any] = {"limit": limit}
    if user_id is not None:
        where += " AND user_id = :user_id"
        params["user_id"] = user_id
    stmt = text(
        f"""
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
        LIMIT :limit
        """
    )
    async with get_connection() as conn:
        result = await conn.execute(stmt, params)
        rows = result.fetchall()
    return [_row_to_dict(r) for r in rows]


async def load_thread_history(
    thread_id: str,
    *,
    user_id: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Return the most recent N exchanges in chronological (oldest-first) order.

    The agent uses this to feed prior turns back into the LLM as
    context. We cap at ``limit`` exchanges so a long thread doesn't
    blow the context window — six round trips (twelve messages) is
    plenty for short-term grounding without overwhelming smaller
    local models.
    """
    rows = await list_recent_messages(
        limit=limit, user_id=user_id, thread_id=thread_id
    )
    return list(reversed(rows))
