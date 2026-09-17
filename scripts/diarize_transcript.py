"""Video/audio -> speaker-labelled transcript, ready for the persona pipeline.

Runs WhisperX (transcription + forced alignment + pyannote diarization) on
one audio/video file, then renders the diarized turns as a plain-text file
using the exact speaker-header format `backend/persona/extraction.parse_turns`
already parses:

    Jonas M
    <his merged turn text>

    Student
    <their merged turn text>

Deliberately does NOT touch `backend/persona/extraction.py` or
`backend/admin_api.py` — the output is a plain .txt meant to be reviewed by
a human and then uploaded through the existing `/admin` Upload tab exactly
like a manually-prepared transcript. This keeps a human in the loop before
anything reaches LLM extraction, and needs zero changes to the
already-working review/train/deploy pipeline.

Runs in its own venv (see scripts/setup_diarize.sh) — WhisperX/pyannote/torch
never touch the backend's dependency set, same convention as `training/`.

Requires a Hugging Face token with the pyannote/speaker-diarization-3.1
model license accepted at https://huggingface.co/pyannote/speaker-diarization-3.1
(one-time, in a browser, under your own HF account — this script can't do
that step for you).

Usage:
    python scripts/diarize_transcript.py \\
        --input data/persona/videos/class-2026-01-10.mp4 \\
        --output data/persona/raw/class-2026-01-10.txt \\
        --hf-token hf_...

    # Wrong speaker auto-picked as the teacher? Override it:
    python scripts/diarize_transcript.py --input ... --output ... \\
        --teacher-speaker-id SPEAKER_01
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_TEACHER_LABEL = "Jonas M"
STUDENT_LABEL = "Student"


def _get_hf_token(cli_token: str | None) -> str:
    token = cli_token or os.environ.get("HF_TOKEN") or os.environ.get(
        "HUGGING_FACE_HUB_TOKEN"
    )
    if not token:
        print(
            "ERROR: no Hugging Face token given. Pass --hf-token, or set "
            "HF_TOKEN in the environment. You also need to accept the "
            "model license once at "
            "https://huggingface.co/pyannote/speaker-diarization-3.1 "
            "under your own HF account before this will work.",
            file=sys.stderr,
        )
        sys.exit(2)
    return token


def _transcribe_and_diarize(
    input_path: Path,
    *,
    hf_token: str,
    device: str,
    compute_type: str,
    model_size: str,
    language: str | None,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Return a flat list of {start, end, text, speaker} dicts, time-ordered."""
    import whisperx

    print(f"Loading WhisperX model {model_size!r} on {device}...", file=sys.stderr)
    asr_model = whisperx.load_model(
        model_size, device=device, compute_type=compute_type, language=language
    )

    print(f"Transcribing {input_path}...", file=sys.stderr)
    audio = whisperx.load_audio(str(input_path))
    result = asr_model.transcribe(audio, batch_size=batch_size)

    print("Aligning word timestamps...", file=sys.stderr)
    align_model, align_metadata = whisperx.load_align_model(
        language_code=result["language"], device=device
    )
    result = whisperx.align(
        result["segments"], align_model, align_metadata, audio, device
    )

    print("Running speaker diarization (pyannote)...", file=sys.stderr)
    diarize_model = whisperx.diarize.DiarizationPipeline(
        use_auth_token=hf_token, device=device
    )
    diarize_segments = diarize_model(audio)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    segments: list[dict[str, Any]] = []
    for seg in result["segments"]:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": text,
                # WhisperX leaves "speaker" unset for segments it couldn't
                # attribute (e.g. cross-talk) — bucket those as "UNKNOWN"
                # rather than crashing; they'll collapse into Student below.
                "speaker": seg.get("speaker") or "UNKNOWN",
            }
        )
    return segments


def _pick_teacher_speaker(
    segments: list[dict[str, Any]], override: str | None
) -> tuple[str, dict[str, float]]:
    talk_time: dict[str, float] = defaultdict(float)
    for seg in segments:
        talk_time[seg["speaker"]] += seg["end"] - seg["start"]
    if not talk_time:
        raise RuntimeError("no speakers detected — is the audio silent?")
    teacher_id = override or max(talk_time, key=lambda k: talk_time[k])
    return teacher_id, dict(talk_time)


def _merge_into_turns(
    segments: list[dict[str, Any]], *, teacher_id: str, teacher_label: str
) -> list[tuple[str, str]]:
    """Collapse consecutive same-speaker segments into (label, text) turns."""
    turns: list[tuple[str, str]] = []
    current_label: str | None = None
    current_parts: list[str] = []

    def label_for(speaker_id: str) -> str:
        return teacher_label if speaker_id == teacher_id else STUDENT_LABEL

    for seg in segments:
        label = label_for(seg["speaker"])
        if label != current_label:
            if current_label is not None and current_parts:
                turns.append((current_label, " ".join(current_parts)))
            current_label = label
            current_parts = []
        current_parts.append(seg["text"])
    if current_label is not None and current_parts:
        turns.append((current_label, " ".join(current_parts)))
    return turns


def _render(turns: list[tuple[str, str]]) -> str:
    blocks = [f"{label}\n{text}" for label, text in turns]
    return "\n\n".join(blocks) + "\n"


def _print_speaker_summary(
    talk_time: dict[str, float], teacher_id: str, teacher_label: str
) -> None:
    print("\nSpeaker summary (by total talk time):", file=sys.stderr)
    for speaker_id, seconds in sorted(
        talk_time.items(), key=lambda kv: kv[1], reverse=True
    ):
        picked = f" -> {teacher_label}" if speaker_id == teacher_id else " -> Student"
        minutes = seconds / 60
        print(f"  {speaker_id}: {minutes:.1f} min{picked}", file=sys.stderr)
    print(
        "\nIf the wrong speaker was picked as the teacher, rerun with "
        "--teacher-speaker-id <id>.\n",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Audio/video file.")
    parser.add_argument(
        "--output", required=True, type=Path, help="Output .txt path."
    )
    parser.add_argument(
        "--teacher-label",
        default=DEFAULT_TEACHER_LABEL,
        help=f"Header text for the teacher's turns (default: {DEFAULT_TEACHER_LABEL!r}, "
        "matches PERSONA_TARGET_SPEAKER).",
    )
    parser.add_argument(
        "--teacher-speaker-id",
        default=None,
        help="Override the auto-detected teacher speaker id (e.g. SPEAKER_01) "
        "when the most-talk-time heuristic picks wrong.",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help="Hugging Face token (or set HF_TOKEN env var). Must have accepted "
        "the pyannote/speaker-diarization-3.1 license.",
    )
    parser.add_argument("--device", default="cuda", help="cuda or cpu.")
    parser.add_argument(
        "--compute-type",
        default="float16",
        help="WhisperX compute type (float16 on GPU, int8 on CPU).",
    )
    parser.add_argument(
        "--model", default="large-v3", help="WhisperX/faster-whisper model size."
    )
    parser.add_argument(
        "--language", default=None, help="Force a language code (default: auto-detect)."
    )
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        return 2

    hf_token = _get_hf_token(args.hf_token)

    segments = _transcribe_and_diarize(
        args.input,
        hf_token=hf_token,
        device=args.device,
        compute_type=args.compute_type,
        model_size=args.model,
        language=args.language,
        batch_size=args.batch_size,
    )
    if not segments:
        print("ERROR: no speech detected in input", file=sys.stderr)
        return 1

    teacher_id, talk_time = _pick_teacher_speaker(segments, args.teacher_speaker_id)
    _print_speaker_summary(talk_time, teacher_id, args.teacher_label)

    turns = _merge_into_turns(
        segments, teacher_id=teacher_id, teacher_label=args.teacher_label
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_render(turns), encoding="utf-8")

    teacher_turns = sum(1 for label, _ in turns if label == args.teacher_label)
    print(
        f"Wrote {len(turns)} turn(s) ({teacher_turns} from {args.teacher_label!r}) "
        f"to {args.output}",
        file=sys.stderr,
    )
    print(
        "Next: review the file, then upload it via the /admin Upload tab "
        "(target speaker defaults to PERSONA_TARGET_SPEAKER in .env).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
