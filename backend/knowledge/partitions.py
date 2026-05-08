"""Mapping between knowledge domains and ChromaDB collections.

Keeping this central means agents and ingestion code agree on which
collection holds which corpus.
"""

from __future__ import annotations

from typing import Final

from ..schemas import AgentName

AGENT_TO_COLLECTION: Final[dict[AgentName, str]] = {
    "vedic_scholar": "vedic_texts",
    "sanskrit_grammar": "vedic_texts",
    "communication": "communications",
    "infosec": "communications",
    "survival": "survival_knowledge",
    "media": "media_index",
}


def collection_for(agent: AgentName) -> str:
    return AGENT_TO_COLLECTION[agent]
