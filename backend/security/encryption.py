"""AES-GCM encryption helpers for PII at rest.

Phase 1 surface only — used by Phase 4 once user-PII columns land. Keep
the API stable so call-sites don't churn between phases.

The key is read from `ENCRYPTION_KEY` (hex-encoded 32 bytes).
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings

NONCE_BYTES = 12


class EncryptionConfigError(RuntimeError):
    """Raised when ENCRYPTION_KEY is missing or malformed."""


@lru_cache(maxsize=1)
def _key() -> bytes:
    raw = get_settings().encryption_key
    if not raw or raw == "dev-only-change-me":
        raise EncryptionConfigError(
            "ENCRYPTION_KEY is not configured. "
            "Generate one with `openssl rand -hex 32` and set it in .env."
        )
    try:
        key = bytes.fromhex(raw)
    except ValueError as exc:
        raise EncryptionConfigError("ENCRYPTION_KEY must be hex-encoded.") from exc
    if len(key) not in (16, 24, 32):
        raise EncryptionConfigError(
            f"ENCRYPTION_KEY must be 16, 24, or 32 bytes; got {len(key)}."
        )
    return key


def encrypt(plaintext: str) -> str:
    """AES-GCM encrypt a string. Returns base64(nonce || ciphertext || tag)."""
    aesgcm = AESGCM(_key())
    nonce = os.urandom(NONCE_BYTES)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str) -> str:
    """Inverse of `encrypt`."""
    blob = base64.b64decode(token.encode("ascii"))
    nonce, ct = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    pt = AESGCM(_key()).decrypt(nonce, ct, associated_data=None)
    return pt.decode("utf-8")
