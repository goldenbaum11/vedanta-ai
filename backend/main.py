"""FastAPI entrypoint for Vedanta AI.

API surface (through Phase 2):
    GET  /health                — liveness + dependency probes (LLM, Chroma)
    POST /api/v1/chat           — classify, dispatch, persist, return one JSON
    POST /api/v1/chat/stream    — same, but ndjson-streamed token-by-token
    GET  /api/v1/agents         — list of supported agents
    GET  /api/v1/messages       — recent message history (admin/per-user)
    POST /api/v1/auth/register  — create account, return JWT
    POST /api/v1/auth/login     — exchange credentials for a JWT
    GET  /api/v1/auth/me        — current authenticated profile

This module wires together: config, database, RAG bootstrap, intent
classifier, dispatcher, audit logging, JWT auth, and rate limiting.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import database
from .config import get_settings
from .models.llm_client import get_llm_client
from .rag import vector_store
from .router import dispatcher, intent_classifier
from .schemas import (
    AGENT_NAMES,
    ChatRequest,
    ChatResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserProfile,
)
from .security import audit_log, auth
from .security.auth import AuthenticatedUser
from .security.rate_limit import auth_limit, chat_limit, limiter, wire_rate_limiter

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
    wire_rate_limiter(app)

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

    async def _resolve_intent(
        req: ChatRequest,
    ) -> intent_classifier.IntentResult:
        if req.agent_override is not None:
            return intent_classifier.IntentResult(
                agent=req.agent_override,
                confidence=1.0,
                rationale="user_override",
            )
        return await intent_classifier.classify(req.message)

    @app.post("/api/v1/chat", response_model=ChatResponse)
    @limiter.limit(chat_limit)
    async def chat(
        req: ChatRequest,
        request: Request,
        user: AuthenticatedUser | None = Depends(auth.current_user_optional),
    ) -> ChatResponse:
        client_ip = request.client.host if request.client else None
        if user is not None and not req.user_id:
            req.user_id = user.subject
        intent = await _resolve_intent(req)

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
            citations=agent_response.citations,
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

    @app.post("/api/v1/chat/stream")
    @limiter.limit(chat_limit)
    async def chat_stream(
        req: ChatRequest,
        request: Request,
        user: AuthenticatedUser | None = Depends(auth.current_user_optional),
    ) -> StreamingResponse:
        """Streaming sibling of `/api/v1/chat`.

        Emits newline-delimited JSON events:
            {"type":"intent",   "agent","confidence","rationale"}
            {"type":"meta",     "agent","citations","escalate","metadata"}
            {"type":"token",    "delta":"..."}    (zero or more)
            {"type":"done",     "text","created_at"}
            {"type":"error",    "message","text"}

        Content-Type: application/x-ndjson. The client should read the
        body as a stream and parse each line as it arrives.
        """
        client_ip = request.client.host if request.client else None
        if user is not None and not req.user_id:
            req.user_id = user.subject
        intent = await _resolve_intent(req)

        async def generator() -> AsyncIterator[bytes]:
            def encode(event: dict[str, Any]) -> bytes:
                return (json.dumps(event, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                )

            yield encode(
                {
                    "type": "intent",
                    "agent": intent.agent,
                    "confidence": intent.confidence,
                    "rationale": intent.rationale,
                }
            )

            text_parts: list[str] = []
            captured_citations: list[dict[str, Any]] = []
            captured_metadata: dict[str, Any] = {}
            captured_escalate = False
            captured_error: str | None = None
            final_text: str | None = None
            saw_terminal = False  # True once we've forwarded done|error from the agent

            try:
                async for event in dispatcher.dispatch_stream(
                    agent=intent.agent,
                    query=req.message,
                    context={
                        "user_id": req.user_id,
                        "intent": intent.model_dump(),
                    },
                ):
                    etype = event.get("type")
                    if etype == "meta":
                        captured_citations = list(event.get("citations") or [])
                        captured_metadata = dict(event.get("metadata") or {})
                        captured_escalate = bool(event.get("escalate"))
                    elif etype == "token":
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            text_parts.append(delta)
                    elif etype == "done":
                        final_text = event.get("text") or "".join(text_parts).strip()
                        # Enrich the agent's terminal event with timestamp.
                        event = {**event, "created_at": datetime.now(timezone.utc).isoformat()}
                        saw_terminal = True
                    elif etype == "error":
                        captured_error = event.get("message") or "stream error"
                        final_text = event.get("text") or "".join(text_parts).strip()
                        saw_terminal = True
                    yield encode(event)
            except ValueError as exc:
                captured_error = str(exc)
                yield encode({"type": "error", "message": str(exc), "text": ""})
                saw_terminal = True
            except Exception as exc:  # noqa: BLE001 - surface, then persist what we have
                logger.exception("chat_stream dispatch failed")
                captured_error = str(exc)
                yield encode({"type": "error", "message": str(exc), "text": ""})
                saw_terminal = True

            persisted_text = (
                final_text if final_text is not None else "".join(text_parts).strip()
            )
            if not saw_terminal:
                # Stream cut off without the agent emitting done|error
                # (e.g. client disconnected, generator cancelled mid-flight).
                yield encode(
                    {
                        "type": "done",
                        "text": persisted_text,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "incomplete": True,
                    }
                )

            try:
                await database.save_message(
                    user_id=req.user_id,
                    agent=intent.agent,
                    intent_confidence=intent.confidence,
                    query=req.message,
                    response=persisted_text,
                    metadata={
                        **captured_metadata,
                        "rationale": intent.rationale,
                        "streamed": True,
                        **({"error": captured_error} if captured_error else {}),
                    },
                    citations=captured_citations,
                )
                await audit_log.record(
                    endpoint="/api/v1/chat/stream",
                    method="POST",
                    user_id=req.user_id,
                    ip_address=client_ip,
                    status_code=200 if not captured_error else 500,
                    detail=(
                        f"agent={intent.agent} "
                        f"confidence={intent.confidence:.2f} "
                        f"escalate={captured_escalate} "
                        f"error={captured_error or '-'}"
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - persistence failure shouldn't blow up the stream
                logger.exception("chat_stream persistence failed: %s", exc)

        return StreamingResponse(
            generator(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/messages")
    async def messages(
        limit: int = 50,
        user_id: str | None = None,
        user: AuthenticatedUser | None = Depends(auth.current_user_optional),
    ) -> dict[str, list[dict[str, object]]]:
        if limit <= 0 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be in (0, 500]")
        # Authenticated users can only see their own history. Anonymous
        # callers may pass `user_id` (their localStorage id) to scope.
        if user is not None:
            user_id = user.subject
        rows = await database.list_recent_messages(limit=limit, user_id=user_id)
        return {"messages": rows}

    @app.post("/api/v1/auth/register", response_model=TokenResponse)
    @limiter.limit(auth_limit)
    async def register(req: RegisterRequest, request: Request) -> TokenResponse:
        client_ip = request.client.host if request.client else None
        try:
            user_id = await auth.create_user(email=req.email, password=req.password)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        row = await auth.fetch_user_by_id(user_id)
        if row is None:
            raise HTTPException(status_code=500, detail="failed to create user")
        token = auth.create_access_token(
            user_id=int(row["id"]), email=row["email"], role=row["role"]
        )
        await audit_log.record(
            endpoint="/api/v1/auth/register",
            method="POST",
            user_id=f"user:{row['id']}",
            ip_address=client_ip,
            status_code=201,
            detail=f"email={row['email']}",
        )
        return TokenResponse(
            access_token=token,
            expires_in=int(get_settings().jwt_expire_minutes) * 60,
            user={"id": row["id"], "email": row["email"], "role": row["role"]},
        )

    @app.post("/api/v1/auth/login", response_model=TokenResponse)
    @limiter.limit(auth_limit)
    async def login(req: LoginRequest, request: Request) -> TokenResponse:
        client_ip = request.client.host if request.client else None
        row = await auth.fetch_user_by_email(req.email)
        if row is None or not auth.verify_password(req.password, row["password_hash"]):
            await audit_log.record(
                endpoint="/api/v1/auth/login",
                method="POST",
                user_id=None,
                ip_address=client_ip,
                status_code=401,
                detail=f"failed_login email={req.email.lower()}",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials.",
            )
        token = auth.create_access_token(
            user_id=int(row["id"]), email=row["email"], role=row["role"]
        )
        await audit_log.record(
            endpoint="/api/v1/auth/login",
            method="POST",
            user_id=f"user:{row['id']}",
            ip_address=client_ip,
            status_code=200,
            detail=f"email={row['email']}",
        )
        return TokenResponse(
            access_token=token,
            expires_in=int(get_settings().jwt_expire_minutes) * 60,
            user={"id": row["id"], "email": row["email"], "role": row["role"]},
        )

    @app.get("/api/v1/auth/me", response_model=UserProfile)
    async def me(
        user: AuthenticatedUser = Depends(auth.current_user),
    ) -> UserProfile:
        return UserProfile(id=user.id, email=user.email, role=user.role)

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
