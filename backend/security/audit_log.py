"""Audit log facade.

Phase 1: thin wrapper over `database.write_audit_log` so route handlers
have a single import to reach for. Phase 4 will add tamper-evident
hashing and encrypted-at-rest detail fields.
"""

from __future__ import annotations

from .. import database


async def record(
    *,
    endpoint: str,
    method: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    status_code: int | None = None,
    detail: str | None = None,
) -> None:
    """Persist a single audit entry."""
    await database.write_audit_log(
        user_id=user_id,
        endpoint=endpoint,
        method=method,
        ip_address=ip_address,
        status_code=status_code,
        detail=detail,
    )
