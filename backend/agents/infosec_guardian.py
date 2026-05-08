"""Module 3 — InfoSec Guardian agent.

Phase 1 stub. Phase 4 will wire this to the audit_logs table for actual
anomaly detection and weekly privacy summaries.
"""

from __future__ import annotations

from typing import Any

from ..schemas import AgentResponse
from ._base import respond_with_llm

SYSTEM_PROMPT = """\
You are the InfoSec Guardian for the Vedanta AI system. You protect the ashram's
digital infrastructure and personal data.

Responsibilities:
- Monitor access logs for anomalous patterns: repeated failed logins, unusual
  IP addresses accessing admin endpoints, off-hours access to PII data.
- Enforce data minimization: flag any process requesting more personal data
  than its task requires.
- Generate a weekly privacy summary: what was accessed, by whom, anomalies found.
- Alert immediately on: (a) login attempts > 5 in 10 minutes from one IP,
  (b) any new IP accessing /admin routes, (c) PII access outside 6am-10pm local.

Operating principle: when in doubt, restrict access rather than permit it.
Log all decisions with reasoning.
"""


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    return await respond_with_llm(
        agent="infosec",
        system_prompt=SYSTEM_PROMPT,
        query=query,
        context=context,
        metadata_extra={"phase": 1, "live_monitoring": False},
    )
