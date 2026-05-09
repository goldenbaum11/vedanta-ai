"""ChromaDB vector-store wrapper.

Provides a single persistent client and named collections per knowledge
domain. The active embedding function (configured via `EMBEDDING_PROVIDER`)
is bound to every collection at creation time, so do NOT mix providers
without resetting the collection — the vector dimensions will differ.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Iterable

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from ..config import get_settings
from ..models.embedding_client import get_embedding_function

logger = logging.getLogger(__name__)

COLLECTION_NAMES: tuple[str, ...] = (
    "vedic_texts",
    "survival_knowledge",
    "communications",
    "media_index",
)

_client: ClientAPI | None = None
_lock = threading.Lock()


def _get_client() -> ClientAPI:
    """Lazily create a thread-safe persistent ChromaDB client."""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            persist_dir = Path(get_settings().chroma_persist_dir)
            persist_dir.mkdir(parents=True, exist_ok=True)
            _client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
    return _client


def _collection_kwargs() -> dict[str, Any]:
    """Common kwargs passed to every get/create call.

    Pulls in the active embedding function so all collections agree on
    vector space.
    """
    kwargs: dict[str, Any] = {}
    embedding_fn = get_embedding_function()
    if embedding_fn is not None:
        kwargs["embedding_function"] = embedding_fn
    return kwargs


def ensure_collections() -> dict[str, Collection]:
    """Create all canonical collections if missing and return them."""
    client = _get_client()
    collections: dict[str, Collection] = {}
    for name in COLLECTION_NAMES:
        collections[name] = client.get_or_create_collection(name=name, **_collection_kwargs())
    return collections


def get_collection(name: str) -> Collection:
    """Fetch (or create) a collection by name."""
    if name not in COLLECTION_NAMES:
        logger.warning("Requesting non-canonical collection: %s", name)
    return _get_client().get_or_create_collection(name=name, **_collection_kwargs())


def reset_collection(name: str) -> Collection:
    """Delete and recreate a collection. Used when changing embedding providers."""
    client = _get_client()
    try:
        client.delete_collection(name=name)
    except Exception as exc:  # noqa: BLE001 - chroma raises various NotFound-like errors
        logger.debug("delete_collection(%s) ignored: %s", name, exc)
    return client.get_or_create_collection(name=name, **_collection_kwargs())


def add_documents(
    *,
    collection_name: str,
    documents: Iterable[str],
    metadatas: Iterable[dict[str, Any]] | None = None,
    ids: Iterable[str] | None = None,
) -> int:
    """Insert documents into the named collection. Returns count added."""
    collection = get_collection(collection_name)
    docs = list(documents)
    metas = list(metadatas) if metadatas is not None else None
    doc_ids = (
        list(ids)
        if ids is not None
        else [f"{collection_name}:{i}" for i in range(len(docs))]
    )
    if not docs:
        return 0
    collection.add(documents=docs, metadatas=metas, ids=doc_ids)
    return len(docs)


def query(
    *,
    collection_name: str,
    text: str,
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a similarity query and return a flat list of hits.

    `where` is forwarded to ChromaDB as a metadata filter (e.g.
    `{"chapter": "2"}` or compound `{"$and": [...]}`).
    """
    collection = get_collection(collection_name)
    kwargs: dict[str, Any] = {"query_texts": [text], "n_results": n_results}
    if where:
        kwargs["where"] = where
    raw = collection.query(**kwargs)
    hits: list[dict[str, Any]] = []
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    ids = (raw.get("ids") or [[]])[0]
    for idx, doc in enumerate(docs):
        hits.append(
            {
                "id": ids[idx] if idx < len(ids) else None,
                "document": doc,
                "metadata": metas[idx] if idx < len(metas) else {},
                "distance": distances[idx] if idx < len(distances) else None,
            }
        )
    return hits


def is_available() -> bool:
    """Reachability probe used by `/health`."""
    try:
        _get_client().heartbeat()
        return True
    except Exception as exc:  # noqa: BLE001 - report any failure as unavailable
        logger.debug("ChromaDB heartbeat failed: %s", exc)
        return False
