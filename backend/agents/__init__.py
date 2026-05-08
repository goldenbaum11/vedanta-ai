"""Agent modules.

Each agent exposes a single async entry point::

    async def handle(query: str, context: dict) -> AgentResponse

Agents must never import from each other — all routing is the dispatcher's
responsibility (see `backend/router/dispatcher.py`).
"""
