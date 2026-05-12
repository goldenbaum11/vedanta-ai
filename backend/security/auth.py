"""Authentication primitives: password hashing + JWT issue/verify.

Design goals
------------
1. **Optional** — Phase 1/2 routes still work without auth so the
   existing anonymous browser flow keeps working. Use `current_user`
   to require auth, `current_user_optional` to allow either.
2. **Local-first** — secrets live in `.env` (`SECRET_KEY`), no third
   parties involved.
3. **Cheap** — bcrypt via `passlib`, JWT via `python-jose`. Both are
   already in `backend/requirements.txt`.

Wire format
-----------
- Token type: HS256 JWT.
- Claims: `sub` = user id (int as string), `email`, `role`, `iat`, `exp`.
- Lifetime: configurable via `JWT_EXPIRE_MINUTES`, default 24 h.
- Header: `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text

from .. import database
from ..config import get_settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 60 * 24

_bearer = HTTPBearer(auto_error=False)

# bcrypt's algorithmic ceiling — anything past this is silently
# discarded by the algorithm. Truncate at the source so behavior is
# consistent regardless of bcrypt version.
BCRYPT_MAX_PASSWORD_BYTES = 72


def _truncate_for_bcrypt(plaintext: str) -> bytes:
    encoded = plaintext.encode("utf-8")
    if len(encoded) <= BCRYPT_MAX_PASSWORD_BYTES:
        return encoded
    return encoded[:BCRYPT_MAX_PASSWORD_BYTES]


@dataclass(frozen=True)
class AuthenticatedUser:
    """Minimal authenticated-user record propagated into route handlers."""

    id: int
    email: str
    role: str

    @property
    def subject(self) -> str:
        """Stable subject identifier for rate-limit keys, message rows, etc."""
        return f"user:{self.id}"


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of `plaintext` as a UTF-8 string."""
    digest = bcrypt.hashpw(_truncate_for_bcrypt(plaintext), bcrypt.gensalt())
    return digest.decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(
            _truncate_for_bcrypt(plaintext), hashed.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def _expire_minutes() -> int:
    settings = get_settings()
    minutes = getattr(settings, "jwt_expire_minutes", None) or DEFAULT_EXPIRE_MINUTES
    return int(minutes)


def create_access_token(*, user_id: int, email: str, role: str) -> str:
    """Issue a signed JWT for `(user_id, email, role)`."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=_expire_minutes())).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc


# --- DB helpers (stay close to the auth flow so they can use the same connection) ---


_FETCH_USER_BY_EMAIL = text(
    "SELECT id, email, role, password_hash FROM users WHERE email = :email"
)
_FETCH_USER_BY_ID = text(
    "SELECT id, email, role, password_hash FROM users WHERE id = :id"
)
_INSERT_USER = text(
    "INSERT INTO users (email, role, password_hash, created_at) "
    "VALUES (:email, :role, :password_hash, :created_at) "
    "RETURNING id"
)


async def fetch_user_by_email(email: str) -> dict[str, Any] | None:
    async with database.get_connection() as conn:
        result = await conn.execute(_FETCH_USER_BY_EMAIL, {"email": email.lower()})
        row = result.fetchone()
    return dict(row._mapping) if row else None


async def fetch_user_by_id(user_id: int) -> dict[str, Any] | None:
    async with database.get_connection() as conn:
        result = await conn.execute(_FETCH_USER_BY_ID, {"id": user_id})
        row = result.fetchone()
    return dict(row._mapping) if row else None


async def create_user(*, email: str, password: str, role: str = "student") -> int:
    """Create a user row and return the new id.

    Raises `ValueError` on duplicate email so the route layer can map to a 409.
    """
    email_norm = email.strip().lower()
    if not email_norm or "@" not in email_norm:
        raise ValueError("email must look like an email address")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")

    password_hash = hash_password(password)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        async with database.get_connection() as conn:
            result = await conn.execute(
                _INSERT_USER,
                {
                    "email": email_norm,
                    "role": role,
                    "password_hash": password_hash,
                    "created_at": created_at,
                },
            )
            new_id = result.scalar_one()
            await conn.commit()
            return int(new_id or 0)
    except database.IntegrityError as exc:
        raise ValueError("email already registered") from exc


# --- FastAPI dependencies ---


async def current_user_optional(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser | None:
    """Return the authenticated user, or `None` if no/invalid token.

    Stashes the user on `request.state.user` so the rate limiter can
    pick it up without re-decoding the token.
    """
    if creds is None or not creds.credentials:
        return None
    try:
        payload = decode_access_token(creds.credentials)
    except HTTPException:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        return None
    row = await fetch_user_by_id(user_id)
    if row is None:
        return None
    user = AuthenticatedUser(id=int(row["id"]), email=row["email"], role=row["role"])
    request.state.user = user
    return user


async def current_user(
    user: AuthenticatedUser | None = Depends(current_user_optional),
) -> AuthenticatedUser:
    """Require a valid authenticated user. Raises 401 otherwise."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
