"""Stage 1 of the persona pipeline: speaker-turn extraction (CLI).

Thin wrapper around backend.persona.extraction — the same code the
admin page uses. See that module for the format documentation.

Usage:
    python3 scripts/extract_persona_turns.py \\
        --input "/path/to/Vedanta Life.txt" \\
        --speaker "Jonas M" \\
        --output data/persona/turns/vedanta_life.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.persona import extraction  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        required=True,
        help="Transcript .txt file(s), or directories to scan for .txt files.",
    )
    parser.add_argument("--speaker", default="Jonas M", help="Target speaker label.")
    parser.add_argument(
        "--min-words",
        type=int,
        default=extraction.DEFAULT_MIN_TURN_WORDS,
        help="Skip turns shorter than this (drops 'Yes.' / 'Okay.' fillers).",
    )
    parser.add_argument("--output", type=Path, required=True, help="Destination JSONL.")
    args = parser.parse_args()

    paths: list[Path] = []
    for p in args.input:
        if p.is_dir():
            paths.extend(sorted(p.glob("*.txt")))
        elif p.exists():
            paths.append(p)
        else:
            logger.error("Input not found: %s", p)
            return 2

    all_turns: list[dict[str, object]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        turns = extraction.extract_turns(
            text, target_speaker=args.speaker, min_words=args.min_words
        )
        if not turns:
            logger.warning(
                "Speaker %r not found in %s (found: %s)",
                args.speaker,
                path.name,
                ", ".join(extraction.list_speakers(text)) or "(none)",
            )
            continue
        for t in extraction.turns_to_dicts(turns):
            all_turns.append({"source": path.name, **t})

    if not all_turns:
        logger.error("No turns extracted for speaker %r", args.speaker)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for turn in all_turns:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    total_words = sum(int(t["word_count"]) for t in all_turns)  # type: ignore[arg-type]
    with_context = sum(1 for t in all_turns if t.get("prev_text"))
    logger.info(
        "Extracted %d turns (%d words) for %r from %d file(s) -> %s",
        len(all_turns),
        total_words,
        args.speaker,
        len(paths),
        args.output,
    )
    logger.info("%d turns have a preceding-speaker context (Q&A candidates)", with_context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
