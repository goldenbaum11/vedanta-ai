"""Shared pytest fixtures.

Each test gets:
- An isolated temporary working directory for SQLite + ChromaDB so tests
  never touch the developer's `vedanta.db` or `data/chroma`.
- Cleared singletons (LLM client, embedding function, ChromaDB client,
  Settings cache) so changes to env vars between tests take effect.
- The sentinel value of `LLM_PROVIDER=ollama` and a deterministic base
  URL so respx mocks bind to a known host.

Tests that need the real local LLM must request the `live_llm` marker
(skipped by default — the suite is fully offline-friendly).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _reset_singletons() -> None:
    from backend import config as _config
    from backend.grammar import sanskrit_heritage as _shp
    from backend.models import embedding_client as _embedding
    from backend.models import llm_client as _llm
    from backend.rag import vector_store as _vs
    from backend.security import rate_limit as _rl

    _config.get_settings.cache_clear()
    _llm.reset_llm_client()
    _embedding.reset_embedding_function()
    _shp.reset_default_parser()
    _vs._client = None  # type: ignore[attr-defined]
    # Limiter holds bucket state in a process-global memory storage.
    # Drop any per-key counters between tests so previous tests don't
    # bleed into rate-limit assertions.
    try:
        _rl.limiter.reset()
    except Exception:  # noqa: BLE001 - best-effort, reset isn't critical
        pass


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the app at a per-test SQLite + ChromaDB directory."""
    db_path = tmp_path / "test.db"
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test")
    monkeypatch.setenv("OLLAMA_DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "http://openai.test/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "default")
    _reset_singletons()
    yield tmp_path
    _reset_singletons()


class _DeterministicEmbedding:
    """Tiny char-bag embedder for fast offline retrieval tests.

    We only need ranking behavior to be stable for tests that exercise
    `hybrid_retrieve` — the *real* retrieval quality is exercised by
    smoke queries against the loaded corpus, not unit tests. Using a
    cheap embedder keeps the test suite under one second per case.
    """

    _DIM = 32

    def name(self) -> str:
        return "deterministic-test"

    def __call__(self, input):  # noqa: A002 - matches ChromaDB signature
        out: list[list[float]] = []
        for text in input:
            vec = [0.0] * self._DIM
            for ch in str(text).lower():
                vec[ord(ch) % self._DIM] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


@pytest.fixture
def in_memory_chroma(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run ChromaDB in EphemeralClient mode with a fast fake embedder."""
    import chromadb

    from backend.rag import vector_store

    ephemeral = chromadb.EphemeralClient()
    monkeypatch.setattr(vector_store, "_client", ephemeral)
    monkeypatch.setattr(
        vector_store, "_collection_kwargs",
        lambda: {"embedding_function": _DeterministicEmbedding()},
    )
    yield
    monkeypatch.setattr(vector_store, "_client", None)
