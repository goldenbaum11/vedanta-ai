"""Local embedding clients.

Provider-agnostic embedding pipeline used by the RAG layer.

Supported backends (selected via `EMBEDDING_PROVIDER`):

- **openai_compatible** — `POST /v1/embeddings` (LM Studio, llama.cpp,
  vLLM). Default; matches the LLM provider so a single LM Studio
  instance can serve both chat and embeddings.
- **ollama** — `POST /api/embed` against a local Ollama daemon
  (e.g. `ollama pull nomic-embed-text`).
- **default** — ChromaDB's bundled `all-MiniLM-L6-v2`. English-only
  but useful as an offline fallback during development.

ChromaDB calls embedding functions synchronously, so this module uses
`httpx`'s sync client rather than `httpx.AsyncClient`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from ..config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingUnavailableError(RuntimeError):
    """Raised when the configured embedding endpoint cannot be reached."""


class OpenAICompatibleEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embed via any OpenAI-compatible `/v1/embeddings` endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds

    def name(self) -> str:
        return f"openai-compatible:{self._model}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def __call__(self, input: Documents) -> Embeddings:
        texts = [str(t) for t in input]
        if not texts:
            return []
        url = f"{self._base_url}/embeddings"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    url,
                    headers=self._headers(),
                    json={"model": self._model, "input": texts},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(
                f"OpenAI-compatible embeddings at {self._base_url} failed: {exc}"
            ) from exc

        items = data.get("data") or []
        if len(items) != len(texts):
            raise EmbeddingUnavailableError(
                f"Embedding count mismatch: requested {len(texts)}, got {len(items)}"
            )
        embeddings: Embeddings = []
        for item in items:
            vec = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vec, list):
                raise EmbeddingUnavailableError("Embedding response missing 'embedding' field.")
            embeddings.append([float(x) for x in vec])
        return embeddings


class OllamaEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embed via Ollama's `/api/embed` endpoint (Ollama 0.2+)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    def name(self) -> str:
        return f"ollama:{self._model}"

    def __call__(self, input: Documents) -> Embeddings:
        texts = [str(t) for t in input]
        if not texts:
            return []
        url = f"{self._base_url}/api/embed"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    url, json={"model": self._model, "input": texts}
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(
                f"Ollama embeddings at {self._base_url} failed: {exc}"
            ) from exc

        vecs = data.get("embeddings") or []
        if len(vecs) != len(texts):
            raise EmbeddingUnavailableError(
                f"Embedding count mismatch: requested {len(texts)}, got {len(vecs)}"
            )
        return [[float(x) for x in v] for v in vecs]


def _build_embedding_function() -> EmbeddingFunction[Documents] | None:
    """Construct the configured embedding function, or `None` for ChromaDB default."""
    settings = get_settings()
    provider = settings.embedding_provider

    if provider == "default":
        return None

    if provider == "openai_compatible":
        return OpenAICompatibleEmbeddingFunction(
            base_url=settings.embedding_base_url
            or settings.openai_compatible_base_url,
            model=settings.embedding_model,
            api_key=settings.embedding_api_key
            or settings.openai_compatible_api_key,
            timeout_seconds=settings.embedding_timeout_seconds,
        )

    if provider == "ollama":
        return OllamaEmbeddingFunction(
            base_url=settings.embedding_base_url or settings.ollama_base_url,
            model=settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
        )

    logger.warning("Unknown EMBEDDING_PROVIDER=%s, falling back to default.", provider)
    return None


_cached_fn: Any = ...  # sentinel — None is a valid value (= use Chroma default)


def get_embedding_function() -> EmbeddingFunction[Documents] | None:
    """Process-wide singleton; returns `None` to mean 'use Chroma's default'."""
    global _cached_fn
    if _cached_fn is ...:
        _cached_fn = _build_embedding_function()
    return _cached_fn


def reset_embedding_function() -> None:
    """Drop the cached function. Useful in tests and after env changes."""
    global _cached_fn
    _cached_fn = ...
