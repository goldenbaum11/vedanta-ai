"""Parse the Vishva Vidya Biblioteca index page into JSONL catalog records.

Input
-----
A markdown export of https://vedanta.com.br/biblioteca (PT or EN). The
page is a catalogue: per-category headers followed by a long line that
runs every text in that category together. Each text entry is a tuple:

    <verse_count> versos<Title><Author><TranslationStatus><Description>

where TranslationStatus is one of the three canonical labels:

    "Tradução confiável" | "Tradução por AI" | "Sem Tradução"
    "Reliable translation" | "AI translation"  | "No Translation"

Output
------
One JSONL record per text, written to
``data/vedic_texts/vishva_vidya_catalog.jsonl``. Each record carries:

* ``source``     — the text title (becomes the citation source in chat)
* ``category``   — Prakaraṇa Granthas, Bhagavad Gītā, Upaniṣads, …
* ``author``     — Śaṅkarācārya, Vyāsa, Tradição Védica, …
* ``verse_count`` — integer
* ``translation_status`` — one of the canonical labels above
* ``description`` — Portuguese (or English) prose blurb
* ``language``    — "pt" or "en", autodetected
* ``tradition``   — "Arsha Vidya / Vishva Vidya" (default for everything
  in Jonas's library)
* ``provenance``  — "vishva_vidya" (so we can filter / delete on request)
* ``source_url``  — best guess at the per-text URL; left as the catalog
  page URL when we don't have the slug yet
* ``record_type`` — "catalog_entry" so the chunker knows this is a
  metadata-only chunk, not a verse with sanskrit/translation/commentary

These records are NOT the verses themselves. They tell the AI what
exists in Jonas's library so it can answer "do you have Tattvabodha?"
type questions and point users back to vedanta.com.br while we wait
for per-text content exports.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Canonical translation status labels, in both languages.
_TRANSLATION_LABELS = (
    "Tradução confiável",
    "Tradução por AI",
    "Sem Tradução",
    "Reliable translation",
    "AI translation",
    "No Translation",
)


# Pattern for the start of an entry: "<digits> versos" or "<digits> verses".
# Allows leading punctuation/whitespace and tolerates the bullet "ediçõe"
# prefix that appears on the Pātañjala Yogasūtra entry.
_ENTRY_SPLIT = re.compile(r"(?:·\s*ediçõe[s]?)?(\d+)\s*versos?", re.IGNORECASE)


@dataclass
class CatalogEntry:
    source: str
    category: str
    author: str
    verse_count: int
    translation_status: str
    description: str
    language: str
    tradition: str
    provenance: str
    source_url: str
    record_type: str


def _detect_language(blob: str) -> str:
    """Crude detector: PT if Portuguese stop-words/diacritics dominate."""
    pt_markers = ("ção", "ões", "tradução", "verso", "está", "português", "técnico")
    en_markers = (" the ", " of ", " and ", "translation", "english", "verses")
    pt_hits = sum(blob.lower().count(m) for m in pt_markers)
    en_hits = sum(blob.lower().count(m) for m in en_markers)
    return "pt" if pt_hits >= en_hits else "en"


def _slugify(title: str) -> str:
    """Best-effort URL slug for a text title.

    Strips diacritics, lowercases, replaces non-alphanumerics with '-'.
    Used only as a heuristic for ``source_url``; the real per-text URL
    slug comes from Vishva Vidya's CMS and will replace these when we
    get the export.
    """
    normalised = unicodedata.normalize("NFKD", title)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "unknown"


def _split_translation_and_description(tail: str) -> tuple[str, str]:
    """Pull the translation-status label out of the front of ``tail``.

    Returns (status, description). If no canonical label is found, the
    status is recorded as "Unknown" and the whole tail is treated as
    the description so we don't silently drop content.
    """
    for label in _TRANSLATION_LABELS:
        if tail.startswith(label):
            return label, tail[len(label):].strip()
    return "Unknown", tail.strip()


def _split_author_and_rest(text: str) -> tuple[str, str]:
    """Split off the author (everything up to the translation label).

    Greedy walk: we know the author always precedes one of the
    canonical translation labels. Find the earliest label and treat
    everything before it as the author.
    """
    earliest_idx = -1
    matched_label = ""
    for label in _TRANSLATION_LABELS:
        idx = text.find(label)
        if idx == -1:
            continue
        if earliest_idx == -1 or idx < earliest_idx:
            earliest_idx = idx
            matched_label = label
    if earliest_idx == -1:
        # No label — give up gracefully.
        return text.strip(), ""
    author = text[:earliest_idx].strip()
    rest = text[earliest_idx:]
    return author, rest


def _parse_category_blob(blob: str, *, category: str, source_page_url: str) -> Iterator[CatalogEntry]:
    """Iterate entries inside one category line."""
    language = _detect_language(blob)
    tradition = "Arsha Vidya / Vishva Vidya"
    provenance = "vishva_vidya"

    # Split on "<N> versos". The result is interleaved:
    #   [prefix, count1, body1, count2, body2, ...]
    parts = _ENTRY_SPLIT.split(blob)
    if len(parts) < 3:
        return

    # parts[0] is whatever comes before the first match — ignore it.
    iterator = iter(parts[1:])
    for count_str, body in zip(iterator, iterator):
        try:
            verse_count = int(count_str)
        except ValueError:
            continue
        body = body.strip()
        if not body:
            continue

        # Title is everything up to the first occurrence of an
        # author-like token. Since titles in the catalog are
        # capitalised words and authors usually start with "Śrī",
        # "Tradição", "Maharṣi" etc., a simpler heuristic works:
        # use the translation-label finder to locate the boundary
        # between title+author and translation+description, then
        # split title from author at the first multi-word author
        # marker.
        title_plus_author, rest = _split_author_and_rest(body)
        if not rest:
            logger.debug("Skipping unparseable entry: %s", body[:80])
            continue
        status, description = _split_translation_and_description(rest)

        title, author = _split_title_and_author(title_plus_author)

        slug = _slugify(title)
        source_url = (
            source_page_url.rstrip("/") + "/" + slug
            if slug != "unknown"
            else source_page_url
        )

        yield CatalogEntry(
            source=title,
            category=category,
            author=author,
            verse_count=verse_count,
            translation_status=status,
            description=description,
            language=language,
            tradition=tradition,
            provenance=provenance,
            source_url=source_url,
            record_type="catalog_entry",
        )


# Author markers — split into "primary" (people / Tradição rubrics) and
# "fallback" (bare Veda names). The Vedas Saṃhitā entries put the Veda
# name in the *title* (e.g. "Atharvaveda Paippalāda — Kāṇḍa 1"), so if
# we matched Veda names first they would win position 0 and steal the
# title. We always try primary markers first; only fall back to Veda
# names when no primary marker is present in the blob.
_PRIMARY_AUTHOR_MARKERS = (
    "Śrī Ādi Śaṅkarācārya / Hastāmalaka",
    "Śrī Ādi Śaṅkarācārya",
    "Śrī Ādi Śaṅkara",
    "Tradição Védica (Yājñavalkya śiṣyas)",
    "Tradição Védica (Tittiri śiṣyas)",
    "Tradição Védica (Atharvan ṛṣis)",
    "Tradição Védica (Ṛṣis)",
    "Tradição Védica",
    "Maharṣi Patañjali",
    "Madhusūdana Sarasvatī",
    "Hastāmalaka",
    "Appayya Dīkṣita",
    "Toṭakācārya",
    "Dharmarāja Adhvarīndra",
    "Sadānanda Yogīndra",
    "Bhāratī Tīrtha",
    "Vācaspati Miśra",
    "Govindānanda",
    "Sureśvarācārya",
    "Ānandagiri",
    "Padmapādācārya",
    "Pūrṇānanda",
    "Vanamālī Miśra",
    "Amalānanda",
    "Śruti + Gauḍapāda + invocações tradicionais",
    "Autor tradicional",
    "Tradição",
)

# Fallback Veda-name markers, used only when the author column on the
# site lists the source Veda (this happens for some Upaniṣads).
_VEDA_AUTHOR_MARKERS = (
    "Kṛṣṇa Yajurveda",
    "Śukla Yajurveda",
    "Sāmaveda",
    "Atharvaveda",
    "Ṛgveda",
)


def _earliest_match(blob: str, markers: tuple[str, ...]) -> tuple[int, str]:
    """Return ``(index, marker)`` of the earliest matching marker, or ``(-1, "")``."""
    earliest_idx = -1
    matched_marker = ""
    for marker in markers:
        idx = blob.find(marker)
        if idx == -1:
            continue
        if earliest_idx == -1 or idx < earliest_idx:
            earliest_idx = idx
            matched_marker = marker
    return earliest_idx, matched_marker


def _split_title_and_author(blob: str) -> tuple[str, str]:
    """Separate the text title from the author within a single string.

    Strategy:
    1. Try primary author markers (people / Tradição rubrics) and use
       the earliest match. These never appear inside titles.
    2. If none match, fall back to Veda-name markers — used for the
       handful of Upaniṣad entries on the site that list the source
       Veda where the author column normally goes.
    """
    idx, marker = _earliest_match(blob, _PRIMARY_AUTHOR_MARKERS)
    if idx == -1:
        idx, marker = _earliest_match(blob, _VEDA_AUTHOR_MARKERS)
    if idx == -1:
        return blob.strip(), "Unknown"
    title = blob[:idx].strip()
    author = blob[idx : idx + len(marker)].strip()
    return title or "Unknown", author


_CATEGORY_HDR = re.compile(r"^##\s+(.+?)\s*$")


def parse_markdown(md_text: str, *, source_page_url: str) -> list[CatalogEntry]:
    """Walk the markdown line by line, harvesting entries per category."""
    entries: list[CatalogEntry] = []
    current_category: str | None = None
    skip_categories = {
        "Seu carrinho",
        "Your cart",
        "Estudo",
        "Sobre",
        "Social",
        "Legal",
        "Recursos",
        "Study",
        "About",
        "Resources",
    }

    for raw_line in md_text.splitlines():
        line = raw_line.rstrip()
        header_match = _CATEGORY_HDR.match(line)
        if header_match:
            heading = header_match.group(1).strip()
            current_category = None if heading in skip_categories else heading
            continue

        # The actual entries live on the long lines containing the
        # "<N> versos" pattern. Ignore everything else.
        if current_category is None or "versos" not in line.lower():
            continue

        entries.extend(
            _parse_category_blob(
                line, category=current_category, source_page_url=source_page_url
            )
        )

    return entries


def write_jsonl(entries: list[CatalogEntry], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Markdown export of the Biblioteca page.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/vedic_texts/vishva_vidya_catalog.jsonl"),
        help="Destination JSONL file.",
    )
    parser.add_argument(
        "--source-page-url",
        default="https://vedanta.com.br/biblioteca",
        help="The catalog page URL — used as the prefix for per-text source_url guesses.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        logger.error("Input file not found: %s", args.input)
        return 2

    md_text = args.input.read_text(encoding="utf-8")
    entries = parse_markdown(md_text, source_page_url=args.source_page_url)
    if not entries:
        logger.warning("No entries parsed from %s", args.input)
        return 1

    write_jsonl(entries, args.output)
    logger.info("Wrote %d catalog entries to %s", len(entries), args.output)

    # Summary by category for sanity-checking.
    by_category: dict[str, int] = {}
    for e in entries:
        by_category[e.category] = by_category.get(e.category, 0) + 1
    logger.info("By category:")
    for category, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        logger.info("  %-30s %d", category, count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
