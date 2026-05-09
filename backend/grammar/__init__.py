"""Deterministic Sanskrit grammar parsers used alongside the LLM.

Currently exposes a single backend — the Inria Sanskrit Heritage
Platform (SHP) — behind an :class:`SanskritParser` interface. The
agent layer calls :func:`get_default_parser` to obtain a parser if
the integration is enabled, falling back to LLM-only analysis
otherwise.
"""

from .sanskrit_heritage import (
    ParseResult,
    SanskritHeritageParser,
    SanskritParser,
    get_default_parser,
)

__all__ = [
    "ParseResult",
    "SanskritHeritageParser",
    "SanskritParser",
    "get_default_parser",
]
