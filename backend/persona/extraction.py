"""Transcript -> speaker turns -> Q&A pairs.

Stage 1 (`extract_turns`) is deterministic text processing: split a
speaker-labelled transcript into turns and keep only the target
speaker's, with the preceding turn as context.

Stage 2 (`extract_pairs`) uses the local LLM as an *extractor* (never
a rewriter): it finds the student questions the teacher reads aloud
inside long monologue turns and pairs each with the teacher's answer,
verbatim. Deterministic post-processing scrubs student names and
dedupes by answer and question.

Both stages are pure-ish functions so the CLI scripts and the admin
API share one implementation.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Awaitable, Callable

from ..models.llm_client import get_llm_client

logger = logging.getLogger(__name__)

LogFn = Callable[[str], Awaitable[None]]

SEGMENT_TARGET_WORDS = 1200
DEFAULT_MIN_TURN_WORDS = 10
DEFAULT_MIN_ANSWER_WORDS = 40

# A speaker header: short, starts with an uppercase letter, and has no
# sentence punctuation anywhere (rejects body-text lines like
# "See you next week. Hadio").
_SPEAKER_HEADER = re.compile(r"^[A-Z][A-Za-z0-9 '\-]{0,39}$")
_SENTENCE_PUNCT = set(".?!,:;\u2026")

_EXTRACTION_SYSTEM_PROMPT = """\
You extract question-and-answer pairs from a Vedanta teacher's class transcript.

The teacher often reads student questions aloud and then answers them.
Your job is to find each distinct question and pair it with the teacher's answer.

Rules:
1. The ANSWER must be the teacher's own words, copied from the transcript.
   Preserve his speaking style completely — keep fillers like "you know",
   his sentence rhythm, his examples. Do NOT summarize, do NOT paraphrase,
   do NOT "improve" his English. You may only:
   - fix obvious transcription errors (e.g. "Jappa/Jata/Jalp" -> "japa")
   - drop broken sentence fragments at segment boundaries
2. The QUESTION should be the student's question as the teacher read it.
   If he paraphrased it while reading, use his paraphrase. Write it as a
   clean standalone question.
3. Replace any student names with "the student" (privacy).
4. Skip logistics/announcements (retreat dates, microphone problems,
   schedules) — extract only teaching content.
5. If a segment contains no complete question-answer pair, return an
   empty list.

Return ONLY a JSON array (no markdown fences, no commentary):
[{"question": "...", "answer": "..."}]
"""


# --- Stage 1: speaker turns ------------------------------------------------


@dataclass
class Turn:
    turn_index: int
    speaker: str
    text: str
    prev_speaker: str | None
    prev_text: str | None
    word_count: int


def _is_speaker_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    if any(ch in _SENTENCE_PUNCT for ch in stripped):
        return False
    return bool(_SPEAKER_HEADER.match(stripped))


def _normalize(paragraphs: list[str]) -> str:
    cleaned = [re.sub(r"\s+", " ", p).strip() for p in paragraphs]
    return "\n\n".join(p for p in cleaned if p)


def parse_turns(text: str) -> list[tuple[str, str]]:
    """Return the ordered list of ``(speaker, text)`` turns in a transcript."""
    turns: list[tuple[str, str]] = []
    current_speaker: str | None = None
    buffer: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            buffer.append(" ".join(para))
            para = []

    def flush_turn() -> None:
        nonlocal buffer
        flush_para()
        if current_speaker is not None and buffer:
            turns.append((current_speaker, _normalize(buffer)))
        buffer = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _is_speaker_header(line):
            flush_turn()
            current_speaker = line
            continue
        if not line:
            flush_para()
            continue
        if current_speaker is None:
            continue
        para.append(line)
    flush_turn()
    return turns


def list_speakers(text: str) -> list[str]:
    """Distinct speaker labels in a transcript, in order of appearance."""
    seen: list[str] = []
    for speaker, _ in parse_turns(text):
        if speaker not in seen:
            seen.append(speaker)
    return seen


def extract_turns(
    text: str,
    *,
    target_speaker: str,
    min_words: int = DEFAULT_MIN_TURN_WORDS,
) -> list[Turn]:
    """Stage 1: the target speaker's turns, each with preceding context."""
    all_turns = parse_turns(text)
    out: list[Turn] = []
    for i, (speaker, turn_text) in enumerate(all_turns):
        if speaker != target_speaker:
            continue
        wc = len(turn_text.split())
        if wc < min_words:
            continue
        prev_speaker, prev_text = (None, None)
        if i > 0:
            prev_speaker, prev_text = all_turns[i - 1]
        out.append(
            Turn(
                turn_index=i,
                speaker=speaker,
                text=turn_text,
                prev_speaker=prev_speaker,
                prev_text=prev_text,
                word_count=wc,
            )
        )
    return out


def turns_to_dicts(turns: list[Turn]) -> list[dict[str, Any]]:
    return [asdict(t) for t in turns]


# --- Stage 2: Q&A pair extraction ------------------------------------------


def split_segments(text: str, target_words: int = SEGMENT_TARGET_WORDS) -> list[str]:
    """Split a long turn into ~target_words segments on paragraph boundaries."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    segments: list[str] = []
    current: list[str] = []
    count = 0
    for para in paragraphs:
        wc = len(para.split())
        if current and count + wc > target_words:
            segments.append("\n\n".join(current))
            current, count = [], 0
        current.append(para)
        count += wc
    if current:
        segments.append("\n\n".join(current))
    return segments


def parse_json_array(raw: str) -> list[dict[str, str]]:
    """Parse the LLM's response, tolerating markdown fences and prose."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[dict[str, str]] = []
    for item in data if isinstance(data, list) else []:
        q = (item.get("question") or "").strip() if isinstance(item, dict) else ""
        a = (item.get("answer") or "").strip() if isinstance(item, dict) else ""
        if q and a:
            out.append({"question": q, "answer": a})
    return out


def looks_like_question(text: str) -> bool:
    if "?" in text:
        return True
    lowered = text.lower()
    return any(k in lowered for k in ("how ", "what ", "why ", "can you", "could you"))


def _norm_key(s: str, n: int) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower())[:n]


def scrub_and_dedupe(
    pairs: list[dict[str, Any]],
    *,
    scrub_names: list[str],
    min_answer_words: int = DEFAULT_MIN_ANSWER_WORDS,
) -> list[dict[str, Any]]:
    """Deterministic post-processing: name scrub + two-stage dedupe."""
    if scrub_names:
        name_pattern = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in scrub_names) + r")\b"
        )
        for p in pairs:
            p["question"] = name_pattern.sub("the student", str(p["question"]))
            p["answer"] = name_pattern.sub("the student", str(p["answer"]))

    # Stage 1: collapse pairs sharing the same answer prefix — keep the
    # variant with the longest (most complete) answer.
    by_answer: dict[str, dict[str, Any]] = {}
    for p in pairs:
        if len(str(p["answer"]).split()) < min_answer_words:
            continue
        akey = _norm_key(str(p["answer"]), 120)
        existing = by_answer.get(akey)
        if existing is None or len(str(p["answer"])) > len(str(existing["answer"])):
            by_answer[akey] = p

    # Stage 2: among survivors, drop repeated questions.
    seen_questions: set[str] = set()
    final: list[dict[str, Any]] = []
    for p in by_answer.values():
        qkey = _norm_key(str(p["question"]), 120)
        if qkey in seen_questions:
            continue
        seen_questions.add(qkey)
        final.append(p)
    return final


async def extract_pairs(
    turns: list[dict[str, Any]],
    *,
    scrub_names: list[str] | None = None,
    min_answer_words: int = DEFAULT_MIN_ANSWER_WORDS,
    log: LogFn | None = None,
) -> list[dict[str, Any]]:
    """Stage 2: LLM extraction of Q&A pairs from stage-1 turns.

    ``log`` is an optional async callback — the admin job runner passes
    one that persists lines to the job's log so the UI can stream them.
    """

    async def _log(line: str) -> None:
        logger.info("%s", line)
        if log is not None:
            await log(line)

    client = get_llm_client()
    pairs: list[dict[str, Any]] = []

    for turn in turns:
        prev_text = turn.get("prev_text") or ""
        if prev_text and looks_like_question(prev_text):
            pairs.append(
                {
                    "question": re.sub(r"\s+", " ", prev_text).strip(),
                    "answer": turn["text"],
                    "kind": "cross_speaker_qa",
                    "turn_index": turn["turn_index"],
                    "segment": None,
                }
            )

        segments = split_segments(turn["text"])
        await _log(
            f"Turn {turn['turn_index']} ({turn['word_count']} words) -> "
            f"{len(segments)} segment(s)"
        )
        for seg_idx, segment in enumerate(segments):
            response = await client.complete(
                _EXTRACTION_SYSTEM_PROMPT,
                f"Transcript segment:\n\n{segment}",
                temperature=0.1,
            )
            extracted = parse_json_array(response)
            await _log(f"  segment {seg_idx + 1}/{len(segments)}: {len(extracted)} pair(s)")
            for item in extracted:
                pairs.append(
                    {
                        **item,
                        "kind": "embedded_qa",
                        "turn_index": turn["turn_index"],
                        "segment": seg_idx,
                    }
                )

    final = scrub_and_dedupe(
        pairs,
        scrub_names=scrub_names or [],
        min_answer_words=min_answer_words,
    )
    await _log(
        f"Extracted {len(final)} unique pair(s) "
        f"({sum(1 for p in final if p['kind'] == 'embedded_qa')} embedded, "
        f"{sum(1 for p in final if p['kind'] == 'cross_speaker_qa')} cross-speaker)"
    )
    return final
