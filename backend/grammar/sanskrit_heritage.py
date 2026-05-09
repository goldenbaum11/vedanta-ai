"""Sanskrit Heritage Platform (SHP) async client.

The Inria SHP exposes a CGI-style "Sanskrit Reader" that performs
deterministic morphological analysis on a Sanskrit string. We don't
fully parse its rich HTML output — instead we strip tags, collapse
whitespace, and feed the analyst's text into the LLM prompt as a
structural grounding hint. This is good enough to make the
LLM's grammar breakdown more accurate without hard-coupling our
codebase to SHP's HTML schema, which has been known to drift.

The integration is **opt-in** (``sanskrit_heritage_enabled=False``
by default) and **fail-soft**: any timeout or HTTP error simply
returns ``ParseResult(success=False, …)`` so the caller can fall
back to LLM-only analysis.

Inputs:
- Devanagari is detected automatically (full Unicode block 0900–097F).
- ASCII input is treated according to ``sanskrit_heritage_input_scheme``
  (default ``RN`` ≈ IAST).

Public API:
- :class:`SanskritParser` — Protocol satisfied by any parser backend.
- :class:`SanskritHeritageParser` — concrete HTTP client.
- :func:`get_default_parser` — factory; returns ``None`` when disabled.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParseResult:
    """Outcome of one parser call.

    `analysis` is a compact, plain-text rendition of the parser's
    output, ready to embed in an LLM prompt. When ``success`` is
    False, ``analysis`` is empty and ``error`` carries a short
    diagnostic string.
    """

    success: bool
    parser: str
    analysis: str = ""
    error: str | None = None
    raw_url: str | None = None


class SanskritParser(Protocol):
    """Minimal duck-type implemented by every parser backend."""

    name: str

    async def analyze(self, text: str) -> ParseResult:  # pragma: no cover
        ...


_DEVANAGARI_RANGE = re.compile(r"[\u0900-\u097F]")
_HTML_TAG = re.compile(r"<[^>]+>")
_MULTIPLE_WS = re.compile(r"\s+")


def _is_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI_RANGE.search(text))


def _strip_html(html: str) -> str:
    text = _HTML_TAG.sub(" ", html)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    return _MULTIPLE_WS.sub(" ", text).strip()


def _summarize(text: str, *, max_chars: int = 1200) -> str:
    """Trim to a budget so we don't bloat the LLM prompt."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " …"


class SanskritHeritageParser:
    """Async HTTP client for the Inria Sanskrit Heritage Reader.

    The endpoint URL and input transliteration scheme are read from
    application settings, so callers don't need to know them. Errors
    are caught and returned as ``ParseResult(success=False, …)``.
    """

    name = "sanskrit_heritage"

    def __init__(
        self,
        *,
        base_url: str,
        input_scheme: str = "RN",
        timeout_seconds: float = 8.0,
    ) -> None:
        self._base_url = base_url
        self._input_scheme = input_scheme
        self._timeout = timeout_seconds

    def _params(self, text: str) -> dict[str, str]:
        # Common query parameters for SHP's CGI reader. ``text`` is
        # the input string; ``t`` is the input transliteration
        # scheme (Devanagari content auto-detected). ``font=roma``
        # asks the reader to render in Latin script in its output,
        # which strips/cleans up better than its Devanagari renderer.
        scheme = "deva" if _is_devanagari(text) else self._input_scheme
        return {
            "lex": "SH",  # Sanskrit Heritage lexicon
            "cache": "t",
            "st": "t",  # tagging mode
            "us": "f",
            "font": "roma",
            "t": scheme,
            "text": text,
            "mode": "p",  # parser mode (vs. simple lookup)
        }

    async def analyze(self, text: str) -> ParseResult:
        cleaned = (text or "").strip()
        if not cleaned:
            return ParseResult(
                success=False, parser=self.name, error="empty input"
            )
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._base_url, params=self._params(cleaned))
                response.raise_for_status()
                body = response.text
        except httpx.HTTPError as exc:
            logger.info("SHP call failed (%s); falling back to LLM-only.", exc)
            return ParseResult(
                success=False,
                parser=self.name,
                error=f"http error: {exc}",
                raw_url=self._base_url,
            )

        analysis = _summarize(_strip_html(body))
        if not analysis:
            return ParseResult(
                success=False,
                parser=self.name,
                error="parser returned empty body",
                raw_url=self._base_url,
            )
        return ParseResult(
            success=True,
            parser=self.name,
            analysis=analysis,
            raw_url=self._base_url,
        )


_cached_parser: SanskritParser | None = None


def get_default_parser() -> SanskritParser | None:
    """Return the configured parser, or ``None`` when disabled.

    The result is cached so repeated calls don't re-read settings or
    construct a fresh client. Tests that mutate settings should call
    :func:`reset_default_parser`.
    """
    global _cached_parser
    if _cached_parser is not None:
        return _cached_parser
    settings = get_settings()
    if not settings.sanskrit_heritage_enabled:
        return None
    if not settings.sanskrit_heritage_base_url:
        return None
    _cached_parser = SanskritHeritageParser(
        base_url=settings.sanskrit_heritage_base_url,
        input_scheme=settings.sanskrit_heritage_input_scheme or "RN",
        timeout_seconds=settings.sanskrit_heritage_timeout_seconds,
    )
    return _cached_parser


def reset_default_parser() -> None:
    """Clear the cached parser. Used by tests when settings change."""
    global _cached_parser
    _cached_parser = None
