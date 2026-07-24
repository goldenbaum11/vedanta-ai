"""Stage 2 of the persona pipeline: instruction-pair extraction (CLI).

Thin wrapper around backend.persona.extraction — the same code the
admin page uses. Requires a local LLM (LM Studio / Ollama) configured
via .env; override with e.g. LLM_PROVIDER=openai_compatible.

Usage:
    python3 scripts/build_persona_dataset.py \\
        --input data/persona/turns/vedanta_life.jsonl \\
        --output data/persona/dataset/pairs.jsonl \\
        --scrub-name Fabiana --scrub-name Uma
"""

from __future__ import annotations

import argparse
import asyncio
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


async def run(args: argparse.Namespace) -> int:
    turns = [
        json.loads(line)
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    source_by_index = {t["turn_index"]: t.get("source", args.input.stem) for t in turns}

    pairs = await extraction.extract_pairs(
        turns,
        scrub_names=args.scrub_name,
        min_answer_words=args.min_answer_words,
    )
    for p in pairs:
        p["source"] = source_by_index.get(p["turn_index"], args.input.stem)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    logger.info(
        "Wrote %d pairs (%d embedded, %d cross-speaker) -> %s",
        len(pairs),
        sum(1 for p in pairs if p["kind"] == "embedded_qa"),
        sum(1 for p in pairs if p["kind"] == "cross_speaker_qa"),
        args.output,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Turns JSONL from stage 1.")
    parser.add_argument("--output", type=Path, required=True, help="Destination pairs JSONL.")
    parser.add_argument(
        "--min-answer-words",
        type=int,
        default=extraction.DEFAULT_MIN_ANSWER_WORDS,
        help="Drop pairs with answers shorter than this.",
    )
    parser.add_argument(
        "--scrub-name",
        action="append",
        default=[],
        help="Student name to replace with 'the student' (repeatable).",
    )
    args = parser.parse_args()
    if not args.input.exists():
        logger.error("Input not found: %s", args.input)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
