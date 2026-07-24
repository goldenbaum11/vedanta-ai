"""DB access for the persona pipeline tables.

Same conventions as backend/database.py: SQLAlchemy text() statements
with named parameters, explicit commit per unit of work, plain-dict
rows so callers never touch SQLAlchemy types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from .. import database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result: Any) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in result.fetchall()]


def _row(result: Any) -> dict[str, Any] | None:
    r = result.fetchone()
    return dict(r._mapping) if r else None


# --- Transcripts ------------------------------------------------------------


async def create_transcript(
    *,
    filename: str,
    uploaded_by: str | None,
    content_path: str,
    target_speaker: str,
    word_count: int,
) -> int:
    stmt = text(
        """
        INSERT INTO persona_transcripts
            (filename, uploaded_by, content_path, target_speaker, word_count,
             status, created_at)
        VALUES
            (:filename, :uploaded_by, :content_path, :target_speaker, :word_count,
             'uploaded', :created_at)
        RETURNING id
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(
            stmt,
            {
                "filename": filename,
                "uploaded_by": uploaded_by,
                "content_path": content_path,
                "target_speaker": target_speaker,
                "word_count": word_count,
                "created_at": _now(),
            },
        )
        new_id = result.scalar_one()
        await conn.commit()
        return int(new_id)


async def update_transcript(transcript_id: int, **fields: Any) -> None:
    allowed = {"status", "turn_count", "pair_count", "word_count"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    sets = ", ".join(f"{k} = :{k}" for k in updates)
    stmt = text(f"UPDATE persona_transcripts SET {sets} WHERE id = :id")
    async with database.get_connection() as conn:
        await conn.execute(stmt, {**updates, "id": transcript_id})
        await conn.commit()


async def list_transcripts(limit: int = 100) -> list[dict[str, Any]]:
    stmt = text(
        "SELECT * FROM persona_transcripts ORDER BY id DESC LIMIT :limit"
    )
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"limit": limit})
        return _rows(result)


async def get_transcript(transcript_id: int) -> dict[str, Any] | None:
    stmt = text("SELECT * FROM persona_transcripts WHERE id = :id")
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"id": transcript_id})
        return _row(result)


# --- Pairs ------------------------------------------------------------------


async def insert_pairs(transcript_id: int, pairs: list[dict[str, Any]]) -> int:
    if not pairs:
        return 0
    stmt = text(
        """
        INSERT INTO persona_pairs
            (transcript_id, question, answer, kind, segment, status, created_at)
        VALUES
            (:transcript_id, :question, :answer, :kind, :segment, 'pending', :created_at)
        """
    )
    now = _now()
    async with database.get_connection() as conn:
        for p in pairs:
            await conn.execute(
                stmt,
                {
                    "transcript_id": transcript_id,
                    "question": str(p["question"]),
                    "answer": str(p["answer"]),
                    "kind": str(p.get("kind") or "embedded_qa"),
                    "segment": p.get("segment"),
                    "created_at": now,
                },
            )
        await conn.commit()
    return len(pairs)


async def list_pairs(
    *,
    status: str | None = None,
    transcript_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if transcript_id is not None:
        clauses.append("transcript_id = :transcript_id")
        params["transcript_id"] = transcript_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    stmt = text(f"SELECT * FROM persona_pairs {where} ORDER BY id ASC LIMIT :limit")
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, params)
        return _rows(result)


async def update_pair(
    pair_id: int,
    *,
    status: str | None = None,
    question: str | None = None,
    answer: str | None = None,
) -> dict[str, Any] | None:
    updates: dict[str, Any] = {}
    if status is not None:
        updates["status"] = status
        updates["reviewed_at"] = _now()
    if question is not None:
        updates["question"] = question
    if answer is not None:
        updates["answer"] = answer
    if not updates:
        return await get_pair(pair_id)
    sets = ", ".join(f"{k} = :{k}" for k in updates)
    stmt = text(f"UPDATE persona_pairs SET {sets} WHERE id = :id")
    async with database.get_connection() as conn:
        await conn.execute(stmt, {**updates, "id": pair_id})
        await conn.commit()
    return await get_pair(pair_id)


async def get_pair(pair_id: int) -> dict[str, Any] | None:
    stmt = text("SELECT * FROM persona_pairs WHERE id = :id")
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"id": pair_id})
        return _row(result)


async def dataset_stats() -> dict[str, Any]:
    stmt = text(
        """
        SELECT status, COUNT(*) AS n, SUM(LENGTH(answer)) AS chars
        FROM persona_pairs GROUP BY status
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(stmt)
        rows = _rows(result)
    by_status = {r["status"]: {"count": r["n"], "chars": r["chars"] or 0} for r in rows}
    return {
        "pending": by_status.get("pending", {}).get("count", 0),
        "approved": by_status.get("approved", {}).get("count", 0),
        "rejected": by_status.get("rejected", {}).get("count", 0),
        "target": 500,
    }


# --- Jobs -------------------------------------------------------------------


async def create_job(
    *, kind: str, transcript_id: int | None = None, model_name: str | None = None
) -> int:
    stmt = text(
        """
        INSERT INTO persona_jobs
            (kind, status, transcript_id, model_name, log, created_at, updated_at)
        VALUES
            (:kind, 'queued', :transcript_id, :model_name, '', :now, :now)
        RETURNING id
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(
            stmt,
            {
                "kind": kind,
                "transcript_id": transcript_id,
                "model_name": model_name,
                "now": _now(),
            },
        )
        new_id = result.scalar_one()
        await conn.commit()
        return int(new_id)


async def append_job_log(job_id: int, line: str) -> None:
    stmt = text(
        """
        UPDATE persona_jobs
        SET log = COALESCE(log, '') || :chunk, updated_at = :now
        WHERE id = :id
        """
    )
    async with database.get_connection() as conn:
        await conn.execute(stmt, {"chunk": line + "\n", "now": _now(), "id": job_id})
        await conn.commit()


async def set_job_status(job_id: int, status: str, *, error: str | None = None) -> None:
    stmt = text(
        """
        UPDATE persona_jobs
        SET status = :status, error = :error, updated_at = :now
        WHERE id = :id
        """
    )
    async with database.get_connection() as conn:
        await conn.execute(
            stmt, {"status": status, "error": error, "now": _now(), "id": job_id}
        )
        await conn.commit()


async def get_job(job_id: int) -> dict[str, Any] | None:
    stmt = text("SELECT * FROM persona_jobs WHERE id = :id")
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"id": job_id})
        return _row(result)


async def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT id, kind, status, transcript_id, model_name, error,
               created_at, updated_at
        FROM persona_jobs ORDER BY id DESC LIMIT :limit
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"limit": limit})
        return _rows(result)


# --- Models -----------------------------------------------------------------


async def create_model(
    *, name: str, base_model: str, train_pairs: int, val_pairs: int
) -> int:
    stmt = text(
        """
        INSERT INTO persona_models
            (name, base_model, status, train_pairs, val_pairs, created_at)
        VALUES
            (:name, :base_model, 'training', :train_pairs, :val_pairs, :created_at)
        RETURNING id
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(
            stmt,
            {
                "name": name,
                "base_model": base_model,
                "train_pairs": train_pairs,
                "val_pairs": val_pairs,
                "created_at": _now(),
            },
        )
        new_id = result.scalar_one()
        await conn.commit()
        return int(new_id)


async def update_model(
    model_id: int,
    *,
    status: str | None = None,
    adapter_path: str | None = None,
    notes: str | None = None,
) -> None:
    updates: dict[str, Any] = {}
    if status is not None:
        updates["status"] = status
    if adapter_path is not None:
        updates["adapter_path"] = adapter_path
    if notes is not None:
        updates["notes"] = notes
    if not updates:
        return
    sets = ", ".join(f"{k} = :{k}" for k in updates)
    stmt = text(f"UPDATE persona_models SET {sets} WHERE id = :id")
    async with database.get_connection() as conn:
        await conn.execute(stmt, {**updates, "id": model_id})
        await conn.commit()


async def list_models(limit: int = 50) -> list[dict[str, Any]]:
    stmt = text("SELECT * FROM persona_models ORDER BY id DESC LIMIT :limit")
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"limit": limit})
        return _rows(result)


async def get_model(model_id: int) -> dict[str, Any] | None:
    stmt = text("SELECT * FROM persona_models WHERE id = :id")
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"id": model_id})
        return _row(result)


# --- Deployments --------------------------------------------------------------
# At most one deployment is active at a time. Deploying deactivates the
# previous row and inserts a new active one, so history is preserved.


async def get_active_deployment() -> dict[str, Any] | None:
    """Return the active deployment joined with its model row, or None."""
    stmt = text(
        """
        SELECT d.id AS deployment_id, d.model_id, d.deployed_by, d.created_at,
               m.name, m.base_model, m.adapter_path, m.status,
               m.train_pairs, m.val_pairs
        FROM persona_deployments d
        JOIN persona_models m ON m.id = d.model_id
        WHERE d.active = 1
        ORDER BY d.id DESC
        LIMIT 1
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(stmt)
        return _row(result)


async def set_deployment(model_id: int, *, deployed_by: str | None) -> int:
    """Make `model_id` the live model. Returns the new deployment id."""
    deactivate = text(
        """
        UPDATE persona_deployments
        SET active = 0, deactivated_at = :now
        WHERE active = 1
        """
    )
    insert = text(
        """
        INSERT INTO persona_deployments (model_id, deployed_by, active, created_at)
        VALUES (:model_id, :deployed_by, 1, :now)
        RETURNING id
        """
    )
    now = _now()
    async with database.get_connection() as conn:
        await conn.execute(deactivate, {"now": now})
        result = await conn.execute(
            insert, {"model_id": model_id, "deployed_by": deployed_by, "now": now}
        )
        new_id = result.scalar_one()
        await conn.commit()
        return int(new_id)


async def clear_deployment() -> bool:
    """Deactivate the live deployment (back to the stock pipeline).

    Returns True if something was deactivated.
    """
    stmt = text(
        """
        UPDATE persona_deployments
        SET active = 0, deactivated_at = :now
        WHERE active = 1
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"now": _now()})
        await conn.commit()
        return bool(result.rowcount)


async def list_deployments(limit: int = 20) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT d.id AS deployment_id, d.model_id, d.deployed_by, d.active,
               d.created_at, d.deactivated_at, m.name
        FROM persona_deployments d
        JOIN persona_models m ON m.id = d.model_id
        ORDER BY d.id DESC
        LIMIT :limit
        """
    )
    async with database.get_connection() as conn:
        result = await conn.execute(stmt, {"limit": limit})
        return _rows(result)
