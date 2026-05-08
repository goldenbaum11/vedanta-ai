"""Anomaly detection / runtime monitoring.

Phase 1 is a placeholder so other modules can import without circular
dependencies. Phase 4 will populate it with rate-limit tracking, failed
login windows, off-hours PII access detection, and weekly summary jobs.
"""

from __future__ import annotations

from typing import Any


async def check_request(*, endpoint: str, ip_address: str | None) -> dict[str, Any]:
    """Inspect a request and return any anomaly flags found."""
    return {"endpoint": endpoint, "ip_address": ip_address, "flags": []}


async def weekly_privacy_summary() -> dict[str, Any]:
    """Stub for Phase 4 scheduled job."""
    return {"status": "not_implemented", "phase": 1}
