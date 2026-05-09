"""FastAPI entrypoint for Vedanta AI.

API surface (through Phase 2):
    GET  /health             — liveness + dependency probes (LLM, Chroma)
    POST /api/v1/chat        — classify, dispatch to agent, persist, return
    GET  /api/v1/agents      — list of supported agents
    GET  /api/v1/messages    — recent message history (admin)

This module wires together: config, database, RAG bootstrap, intent
classifier, dispatcher, and audit logging.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import database
from .config import get_settings
from .models.llm_client import get_llm_client
from .rag import vector_store
from .router import dispatcher, intent_classifier
from .schemas import AGENT_NAMES, ChatRequest, ChatResponse
from .security import audit_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("vedanta")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialise persistent dependencies on startup."""
    logger.info("Vedanta AI booting...")
    await database.init_db()
    try:
        vector_store.ensure_collections()
        logger.info("ChromaDB collections ready: %s", ", ".join(vector_store.COLLECTION_NAMES))
    except Exception as exc:  # noqa: BLE001 - chroma init must not block API startup
        logger.warning("ChromaDB init failed (continuing in degraded mode): %s", exc)
    yield
    logger.info("Vedanta AI shutting down.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Vedanta AI",
        version="0.1.0",
        description="Local-first multi-agent AI for an ashram community.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        llm = get_llm_client()
        llm_ok = await llm.is_available()
        provider = getattr(llm, "provider", settings.llm_provider)
        base_url = getattr(llm, "base_url", "")
        chroma_ok = vector_store.is_available()
        collection_counts: dict[str, int] = {}
        if chroma_ok:
            for name in vector_store.COLLECTION_NAMES:
                try:
                    collection_counts[name] = vector_store.get_collection(name).count()
                except Exception:  # noqa: BLE001 - per-collection probe is best-effort
                    collection_counts[name] = -1
        return {
            "status": "ok",
            "phase": 2,
            "dependencies": {
                "llm": {
                    "provider": provider,
                    "reachable": llm_ok,
                    "base_url": base_url,
                    "default_model": llm.default_model,
                },
                "embeddings": {
                    "provider": settings.embedding_provider,
                    "model": settings.embedding_model,
                },
                "chroma": {
                    "reachable": chroma_ok,
                    "collections": collection_counts,
                },
                "database": {"path": str(settings.sqlite_path)},
            },
        }

    @app.get("/api/v1/agents")
    async def list_agents() -> dict[str, list[str]]:
        return {"agents": list(AGENT_NAMES)}

    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, request: Request) -> ChatResponse:
        client_ip = request.client.host if request.client else None

        if req.agent_override is not None:
            intent = intent_classifier.IntentResult(
                agent=req.agent_override,
                confidence=1.0,
                rationale="user_override",
            )
        else:
            intent = await intent_classifier.classify(req.message)

        try:
            agent_response = await dispatcher.dispatch(
                agent=intent.agent,
                query=req.message,
                context={"user_id": req.user_id, "intent": intent.model_dump()},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        await database.save_message(
            user_id=req.user_id,
            agent=intent.agent,
            intent_confidence=intent.confidence,
            query=req.message,
            response=agent_response.text,
            metadata={
                **agent_response.metadata,
                "rationale": intent.rationale,
            },
        )
        await audit_log.record(
            endpoint="/api/v1/chat",
            method="POST",
            user_id=req.user_id,
            ip_address=client_ip,
            status_code=200,
            detail=f"agent={intent.agent} confidence={intent.confidence:.2f}",
        )

        return ChatResponse(
            agent=agent_response.agent,
            text=agent_response.text,
            intent_confidence=intent.confidence,
            citations=agent_response.citations,
            metadata=agent_response.metadata,
            escalate=agent_response.escalate,
            created_at=datetime.now(timezone.utc),
        )

    @app.get("/api/v1/messages")
    async def messages(limit: int = 50) -> dict[str, list[dict[str, object]]]:
        if limit <= 0 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be in (0, 500]")
        rows = await database.list_recent_messages(limit=limit)
        return {"messages": rows}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
