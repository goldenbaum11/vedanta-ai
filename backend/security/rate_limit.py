"""Rate-limiting wired through `slowapi`.

Strategy
--------
- Keying: prefer the authenticated user (`request.state.user.subject`)
  set by `auth.current_user_optional`. Otherwise fall back to the
  client IP. This means a logged-in user gets their own bucket no
  matter which device they're on.
- Limits: distinct buckets for anonymous chat, authenticated chat, and
  the auth endpoints (login/register, intentionally tight to slow
  brute-force attempts). All values are configurable via env so ops
  can tune them without redeploying.

The limiter is created once and exported. `wire_rate_limiter(app)` is
called from `main.create_app()` to register the middleware and the
exception handler.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ..config import get_settings

logger = logging.getLogger(__name__)


def identity_key(request: Request) -> str:
    """Return the rate-limit bucket key for `request`.

    Uses the authenticated user when present, IP otherwise. Falls back
    to a literal "anonymous:unknown" if the IP can't be resolved (e.g.
    in tests with no client info).
    """
    user = getattr(request.state, "user", None) if hasattr(request, "state") else None
    if user is not None:
        return getattr(user, "subject", None) or f"user:{getattr(user, 'id', '?')}"
    ip = get_remote_address(request)
    return f"ip:{ip or 'unknown'}"


_settings = get_settings()
limiter = Limiter(
    key_func=identity_key,
    default_limits=[],
    # Disabled because slowapi's header injection requires every
    # rate-limited handler to accept a `response: Response` arg,
    # which conflicts with FastAPI's response_model-driven returns.
    # The 429 response itself still carries `Retry-After`.
    headers_enabled=False,
    storage_uri="memory://",
)


def chat_limit(key: str) -> str:
    """Per-request lookup so authenticated users get the higher bucket.

    `key` is whatever `identity_key()` returned ("user:N" or "ip:..."),
    which is exactly what we need to pick the right bucket without
    re-reading the request.
    """
    settings = get_settings()
    if isinstance(key, str) and key.startswith("user:"):
        return settings.rate_limit_chat_authenticated or "120/minute"
    return settings.rate_limit_chat_anonymous or "30/minute"


def auth_limit(key: str) -> str:
    settings = get_settings()
    return settings.rate_limit_auth or "10/minute"


def wire_rate_limiter(app: FastAPI) -> None:
    """Attach the limiter and 429 handler to a FastAPI app.

    Notes:
    - We intentionally do NOT add ``SlowAPIMiddleware``. With the
      decorator-based limits we use, the middleware would double-count
      each request (once at middleware time, once at decorator time).
    - Each call to ``create_app()`` re-runs ``@limiter.limit(...)`` on
      the route handlers, which appends to ``limiter`` internal
      registries. Tests instantiate the app multiple times, so we
      reset those registries here. In production this runs exactly
      once at import time, so the reset is a no-op.
    """
    _reset_limiter_registries()
    app.state.limiter = limiter

    async def _handler(request: Request, exc: Exception) -> Any:
        return _rate_limit_exceeded_handler(request, exc)  # type: ignore[arg-type]

    app.add_exception_handler(RateLimitExceeded, _handler)


def _reset_limiter_registries() -> None:
    """Clear per-route entries so re-instantiating the app doesn't stack limits.

    These are private slowapi attributes; we touch them defensively so
    a future rename only breaks tests, not prod paths.
    """
    for attr in (
        "_route_limits",
        "_dynamic_route_limits",
        "_default_limits",
        "_application_limits",
        "_exempt_routes",
        "_request_filters",
    ):
        if hasattr(limiter, attr):
            try:
                getattr(limiter, attr).clear()
            except Exception:  # noqa: BLE001 - some attrs are dicts, others lists
                pass
    # Name-mangled private attribute used by Limiter to track which
    # functions have been decorated.
    marked = getattr(limiter, "_Limiter__marked_for_limiting", None)
    if isinstance(marked, dict):
        marked.clear()
