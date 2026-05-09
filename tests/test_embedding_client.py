"""Embedding client tests.

ChromaDB calls embedding functions synchronously, so we use respx to
mock the synchronous httpx calls. Chroma normalizes return values into
numpy arrays; we convert back to plain lists for comparison.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.models.embedding_client import (
    EmbeddingUnavailableError,
    OllamaEmbeddingFunction,
    OpenAICompatibleEmbeddingFunction,
)


pytestmark = pytest.mark.usefixtures("isolated_env")


def _to_lists(vectors: object) -> list[list[float]]:
    """Coerce numpy arrays / nested sequences into plain Python lists."""
    return [[float(x) for x in vec] for vec in vectors]  # type: ignore[union-attr]


def test_openai_embedding_happy_path() -> None:
    with respx.mock(base_url="http://openai.test/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"embedding": [0.1, 0.2, 0.3]},
                        {"embedding": [0.4, 0.5, 0.6]},
                    ]
                },
            )
        )
        fn = OpenAICompatibleEmbeddingFunction(
            base_url="http://openai.test/v1",
            model="nomic-embed-text-v1.5",
            api_key="key",
        )
        vectors = _to_lists(fn(["hello", "world"]))
    assert vectors[0] == pytest.approx([0.1, 0.2, 0.3])
    assert vectors[1] == pytest.approx([0.4, 0.5, 0.6])


def test_openai_embedding_count_mismatch_raises() -> None:
    with respx.mock(base_url="http://openai.test/v1") as router:
        router.post("/embeddings").mock(
            return_value=httpx.Response(
                200, json={"data": [{"embedding": [0.1]}]}
            )
        )
        fn = OpenAICompatibleEmbeddingFunction(
            base_url="http://openai.test/v1", model="m"
        )
        with pytest.raises(EmbeddingUnavailableError):
            fn(["a", "b"])


def test_openai_embedding_http_error_raises() -> None:
    with respx.mock(base_url="http://openai.test/v1") as router:
        router.post("/embeddings").mock(side_effect=httpx.ConnectError("down"))
        fn = OpenAICompatibleEmbeddingFunction(
            base_url="http://openai.test/v1", model="m"
        )
        with pytest.raises(EmbeddingUnavailableError):
            fn(["a"])


def test_ollama_embedding_happy_path() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/embed").mock(
            return_value=httpx.Response(
                200, json={"embeddings": [[1.0, 2.0], [3.0, 4.0]]}
            )
        )
        fn = OllamaEmbeddingFunction(
            base_url="http://ollama.test", model="nomic-embed-text"
        )
        vectors = _to_lists(fn(["a", "b"]))
    assert vectors[0] == pytest.approx([1.0, 2.0])
    assert vectors[1] == pytest.approx([3.0, 4.0])


def test_ollama_embedding_count_mismatch_raises() -> None:
    with respx.mock(base_url="http://ollama.test") as router:
        router.post("/api/embed").mock(
            return_value=httpx.Response(200, json={"embeddings": [[1.0]]})
        )
        fn = OllamaEmbeddingFunction(base_url="http://ollama.test", model="m")
        with pytest.raises(EmbeddingUnavailableError):
            fn(["a", "b"])
