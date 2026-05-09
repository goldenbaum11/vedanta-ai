"""Retriever tests.

Pure functions (`extract_verse_refs`, `format_citations`,
`format_context_block`) get unit tests. The hybrid retrieval path is
exercised against an in-memory ChromaDB with a small synthetic corpus,
which proves that explicit verse references get pinned ahead of pure
semantic results.
"""

from __future__ import annotations

import pytest

from backend.rag import retriever, vector_store


pytestmark = pytest.mark.usefixtures("isolated_env")


def test_extract_verse_refs_finds_multiple_formats() -> None:
    refs = retriever.extract_verse_refs("Compare BG 2.47 and 18.66 with Katha 1:2.")
    assert ("2", "47") in refs
    assert ("18", "66") in refs
    assert ("1", "2") in refs


def test_extract_verse_refs_ignores_plain_numbers() -> None:
    refs = retriever.extract_verse_refs("In year 2026 we ingested 700 verses.")
    assert refs == []


def test_format_citations_carries_full_text_and_snippet() -> None:
    long_doc = "x" * 600
    citations = retriever.format_citations(
        [
            {
                "id": "Bhagavad Gita:2:47",
                "document": long_doc,
                "metadata": {
                    "source": "Bhagavad Gita",
                    "chapter": "2",
                    "verse": "47",
                    "language_tags": "sanskrit, iast, english",
                    "commentary_author": "Shankara",
                    "tradition": "Advaita",
                },
                "distance": 0.123,
            }
        ]
    )
    assert len(citations) == 1
    cit = citations[0]
    assert cit["id"] == "Bhagavad Gita:2:47"
    assert cit["source"] == "Bhagavad Gita"
    assert len(cit["snippet"]) == 280
    assert cit["full_text"] == long_doc
    assert cit["distance"] == pytest.approx(0.123)
    assert cit["language"] == "sanskrit, iast, english"


def test_format_context_block_renders_indexed_headers() -> None:
    block = retriever.format_context_block(
        [
            {
                "id": "BG:2:47",
                "document": "Sanskrit body",
                "metadata": {
                    "source": "Bhagavad Gita",
                    "chapter": "2",
                    "verse": "47",
                    "commentary_author": "Shankara",
                },
            }
        ]
    )
    assert "[1] Bhagavad Gita ch. 2 v. 47 (Shankara)" in block
    assert "Sanskrit body" in block


def test_format_context_block_empty_returns_empty_string() -> None:
    assert retriever.format_context_block([]) == ""


async def test_hybrid_retrieve_pins_exact_verse_references(
    in_memory_chroma: None,
) -> None:
    """Even if pure semantic retrieval ranks BG 2.47 below other chunks,
    the metadata pin guarantees it is in the result set."""
    documents = [
        "[Bhagavad Gita 2.47] You have a right to action only.",
        "[Bhagavad Gita 2.46] Reservoirs and wells.",
        "[Bhagavad Gita 18.66] Surrender unto me.",
        "[Mandukya Upanishad 1.1] AUM is everything.",
        "[Bhagavad Gita 4.7] Whenever dharma declines.",
    ]
    metadatas = [
        {"source": "Bhagavad Gita", "chapter": "2", "verse": "47"},
        {"source": "Bhagavad Gita", "chapter": "2", "verse": "46"},
        {"source": "Bhagavad Gita", "chapter": "18", "verse": "66"},
        {"source": "Mandukya Upanishad", "chapter": "1", "verse": "1"},
        {"source": "Bhagavad Gita", "chapter": "4", "verse": "7"},
    ]
    ids = [
        "Bhagavad Gita:2:47",
        "Bhagavad Gita:2:46",
        "Bhagavad Gita:18:66",
        "Mandukya Upanishad:1:1",
        "Bhagavad Gita:4:7",
    ]
    vector_store.add_documents(
        collection_name="vedic_texts",
        documents=documents,
        metadatas=metadatas,
        ids=ids,
        skip_existing=False,
    )

    hits = await retriever.hybrid_retrieve(
        collection_name="vedic_texts",
        query="What does BG 2.47 say?",
        top_k=3,
    )
    hit_ids = [h["id"] for h in hits]
    assert "Bhagavad Gita:2:47" in hit_ids
    assert hit_ids[0] == "Bhagavad Gita:2:47"


async def test_hybrid_retrieve_dedupes(in_memory_chroma: None) -> None:
    vector_store.add_documents(
        collection_name="vedic_texts",
        documents=["[Bhagavad Gita 2.47] only verse"],
        metadatas=[{"source": "Bhagavad Gita", "chapter": "2", "verse": "47"}],
        ids=["Bhagavad Gita:2:47"],
        skip_existing=False,
    )
    hits = await retriever.hybrid_retrieve(
        collection_name="vedic_texts", query="BG 2.47 commentary", top_k=5
    )
    ids = [h["id"] for h in hits]
    assert ids.count("Bhagavad Gita:2:47") == 1
