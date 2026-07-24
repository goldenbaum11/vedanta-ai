"""Persona agent: answers chat with the deployed fine-tuned model.

This agent is NOT routed by the intent classifier. The chat layer
selects it when an admin has deployed a persona model from
/admin/deployment — the deployed LoRA adapter then substitutes the
stock agent pipeline for chat replies.

Generation runs through the MLX runtime in the training venv (a
subprocess per request). That keeps heavy ML deps out of the API
process, at the cost of latency: every call reloads the model, so
replies take tens of seconds. Good enough to trial a persona live;
for real traffic, fuse the adapter to GGUF and serve it from
LM Studio/Ollama as the default model instead.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from ..persona import jobs as persona_jobs
from ..persona import store as persona_store
from ..schemas import AgentResponse
from ._base import StreamEvent

logger = logging.getLogger(__name__)

_NO_DEPLOYMENT_TEXT = (
    "[persona] No persona model is deployed. An admin can deploy one "
    "from the Deployment page in the admin console."
)


async def _generate(query: str) -> tuple[str, dict[str, Any]]:
    """Return (text, metadata) from the active deployment."""
    deployment = await persona_store.get_active_deployment()
    if deployment is None:
        return _NO_DEPLOYMENT_TEXT, {"deployed": False}
    text = await persona_jobs.test_model(int(deployment["model_id"]), query)
    return text, {
        "deployed": True,
        "model": deployment["name"],
        "base_model": deployment["base_model"],
    }


async def handle(query: str, context: dict[str, Any]) -> AgentResponse:
    try:
        text, metadata = await _generate(query)
    except Exception as exc:  # noqa: BLE001 - degrade like other agents do
        logger.exception("persona generation failed")
        return AgentResponse(
            agent="persona",
            text=f"[persona] Generation failed: {exc}",
            metadata={"agent": "persona", "error": str(exc)},
        )
    return AgentResponse(
        agent="persona",
        text=text,
        metadata={"agent": "persona", **metadata},
    )


async def handle_stream(
    query: str, context: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Stream protocol shim: meta → done.

    The MLX subprocess returns the whole completion at once, so there
    are no token events — the protocol explicitly allows zero.
    """
    try:
        text, metadata = await _generate(query)
    except Exception as exc:  # noqa: BLE001
        logger.exception("persona generation failed")
        yield {
            "type": "meta",
            "agent": "persona",
            "citations": [],
            "escalate": False,
            "metadata": {"agent": "persona", "error": str(exc)},
        }
        yield {
            "type": "error",
            "message": str(exc),
            "text": f"[persona] Generation failed: {exc}",
        }
        return
    yield {
        "type": "meta",
        "agent": "persona",
        "citations": [],
        "escalate": False,
        "metadata": {"agent": "persona", **metadata},
    }
    yield {"type": "done", "text": text}
