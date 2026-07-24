"""In-process async job runner for the persona pipeline.

Jobs run as asyncio tasks inside the FastAPI process; every log line
is appended to the job's DB row so the admin UI can poll and render a
live console. Two job kinds:

* ``extraction`` — stage 1 + stage 2 on one uploaded transcript.
  CPU-light; the slow part is local-LLM calls (minutes).
* ``training``  — exports the approved dataset and spawns the MLX
  LoRA trainer as a subprocess (``training/`` has its own venv so
  PyTorch/MLX never pollute the backend environment). Stdout/stderr
  stream into the job log. Only one training job may run at a time.

Deliberately no Celery/Redis: this is a single-admin, occasional-use
workflow on one box. If jobs ever need to survive a server restart,
revisit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from . import PERSONA_SYSTEM_PROMPT
from . import extraction, store

logger = logging.getLogger(__name__)

# Module-level task registry so jobs aren't garbage-collected and we
# can enforce single-flight training.
_tasks: dict[int, asyncio.Task[None]] = {}
_training_lock = asyncio.Lock()

VAL_FRACTION = 0.1


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _persona_dir() -> Path:
    return _project_root() / "data" / "persona"


def _dataset_dir() -> Path:
    return _persona_dir() / "dataset" / "mlx"


def _adapters_dir() -> Path:
    return _persona_dir() / "adapters"


def _training_python() -> Path:
    settings = get_settings()
    override = getattr(settings, "persona_training_python", "") or ""
    if override:
        return Path(override)
    return _project_root() / "training" / ".venv" / "bin" / "python"


def _spawn(job_id: int, coro: Any) -> None:
    task = asyncio.create_task(coro)
    _tasks[job_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(job_id, None))


# --- Extraction job ---------------------------------------------------------


async def start_extraction(transcript_id: int) -> int:
    job_id = await store.create_job(kind="extraction", transcript_id=transcript_id)
    _spawn(job_id, _run_extraction(job_id, transcript_id))
    return job_id


async def _run_extraction(job_id: int, transcript_id: int) -> None:
    async def log(line: str) -> None:
        await store.append_job_log(job_id, line)

    await store.set_job_status(job_id, "running")
    try:
        transcript = await store.get_transcript(transcript_id)
        if transcript is None:
            raise RuntimeError(f"transcript {transcript_id} not found")
        path = Path(transcript["content_path"])
        text = path.read_text(encoding="utf-8")
        target = transcript["target_speaker"]

        await log(f"Stage 1: extracting turns for {target!r} from {transcript['filename']}")
        speakers = extraction.list_speakers(text)
        await log(f"Speakers found: {', '.join(speakers) or '(none)'}")
        turns = extraction.extract_turns(text, target_speaker=target)
        total_words = sum(t.word_count for t in turns)
        await log(f"Stage 1 done: {len(turns)} turn(s), {total_words} words")
        if not turns:
            raise RuntimeError(
                f"no turns found for speaker {target!r} — check the speaker label"
            )
        await store.update_transcript(
            transcript_id, status="extracting", turn_count=len(turns)
        )

        await log("Stage 2: extracting Q&A pairs with the local LLM...")
        settings = get_settings()
        scrub = [
            n.strip()
            for n in (getattr(settings, "persona_scrub_names", "") or "").split(",")
            if n.strip()
        ]
        pairs = await extraction.extract_pairs(
            extraction.turns_to_dicts(turns), scrub_names=scrub, log=log
        )
        inserted = await store.insert_pairs(transcript_id, pairs)
        await store.update_transcript(
            transcript_id, status="review", pair_count=inserted
        )
        await log(f"Done. {inserted} pair(s) waiting for review.")
        await store.set_job_status(job_id, "succeeded")
    except Exception as exc:  # noqa: BLE001 - job errors land in the job row
        logger.exception("extraction job %d failed", job_id)
        await store.append_job_log(job_id, f"ERROR: {exc}")
        await store.set_job_status(job_id, "failed", error=str(exc))
        try:
            await store.update_transcript(transcript_id, status="failed")
        except Exception:  # noqa: BLE001
            pass


# --- Dataset export ---------------------------------------------------------


async def export_dataset() -> dict[str, Any]:
    """Write approved pairs as MLX-format train/valid JSONL. Returns counts."""
    pairs = await store.list_pairs(status="approved", limit=100_000)
    if not pairs:
        raise ValueError("no approved pairs to export")

    rng = random.Random(42)  # deterministic split — same pairs, same split
    shuffled = list(pairs)
    rng.shuffle(shuffled)
    n_val = max(1, int(len(shuffled) * VAL_FRACTION))
    val, train = shuffled[:n_val], shuffled[n_val:]

    out_dir = _dataset_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    def _write(rows: list[dict[str, Any]], name: str) -> Path:
        path = out_dir / name
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                record = {
                    "messages": [
                        {"role": "system", "content": PERSONA_SYSTEM_PROMPT},
                        {"role": "user", "content": r["question"]},
                        {"role": "assistant", "content": r["answer"]},
                    ]
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    _write(train, "train.jsonl")
    _write(val, "valid.jsonl")
    return {
        "train": len(train),
        "valid": len(val),
        "dir": str(out_dir),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


# --- Training job -----------------------------------------------------------


async def start_training(model_name: str | None = None) -> int:
    for jid in list(_tasks):
        job = await store.get_job(jid)
        if job and job.get("kind") == "training":
            raise ValueError("a training job is already running")
    name = model_name or f"jonas-v{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    job_id = await store.create_job(kind="training", model_name=name)
    _spawn(job_id, _run_training(job_id, name))
    return job_id


async def _run_training(job_id: int, model_name: str) -> None:
    async def log(line: str) -> None:
        await store.append_job_log(job_id, line)

    async with _training_lock:
        await store.set_job_status(job_id, "running")
        model_id: int | None = None
        try:
            settings = get_settings()
            base_model = getattr(
                settings, "persona_base_model", ""
            ) or "mlx-community/Qwen2.5-7B-Instruct-4bit"

            await log(f"Exporting approved dataset for {model_name!r}...")
            export = await export_dataset()
            await log(
                f"Dataset: {export['train']} train / {export['valid']} valid "
                f"-> {export['dir']}"
            )
            model_id = await store.create_model(
                name=model_name,
                base_model=base_model,
                train_pairs=export["train"],
                val_pairs=export["valid"],
            )

            python = _training_python()
            if not python.exists():
                raise RuntimeError(
                    f"training environment not found at {python}. "
                    "Run: cd training && ./setup.sh"
                )

            adapter_path = _adapters_dir() / model_name
            adapter_path.mkdir(parents=True, exist_ok=True)
            # Iters scale with dataset size: ~3 epochs at batch 1.
            iters = max(60, min(1000, export["train"] * 3))
            cmd = [
                str(python),
                "-m",
                "training.train_lora",
                "--base-model", base_model,
                "--data-dir", export["dir"],
                "--adapter-dir", str(adapter_path),
                "--iters", str(iters),
            ]
            await log(f"Launching trainer: {shlex.join(cmd)}")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(_project_root()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    await log(line)
            code = await proc.wait()
            if code != 0:
                raise RuntimeError(f"trainer exited with code {code}")

            await store.update_model(
                model_id, status="ready", adapter_path=str(adapter_path)
            )
            await log(f"Training complete. Adapter saved to {adapter_path}")
            await store.set_job_status(job_id, "succeeded")
        except Exception as exc:  # noqa: BLE001 - job errors land in the job row
            logger.exception("training job %d failed", job_id)
            await store.append_job_log(job_id, f"ERROR: {exc}")
            await store.set_job_status(job_id, "failed", error=str(exc))
            if model_id is not None:
                await store.update_model(model_id, status="failed", notes=str(exc))


# --- Model test (generate with adapter) --------------------------------------


async def test_model(model_id: int, prompt: str, *, max_tokens: int = 400) -> str:
    """Generate one answer with a trained adapter. Blocking-ish (subprocess)."""
    model = await store.get_model(model_id)
    if model is None:
        raise ValueError(f"model {model_id} not found")
    if model["status"] != "ready" or not model.get("adapter_path"):
        raise ValueError(f"model {model['name']} is not ready (status={model['status']})")

    python = _training_python()
    if not python.exists():
        raise RuntimeError(
            f"training environment not found at {python}. Run: cd training && ./setup.sh"
        )

    cmd = [
        str(python),
        "-m",
        "training.generate",
        "--base-model", model["base_model"],
        "--adapter-dir", model["adapter_path"],
        "--system-prompt", PERSONA_SYSTEM_PROMPT,
        "--prompt", prompt,
        "--max-tokens", str(max_tokens),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(_project_root()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("generation timed out after 600s")
    if proc.returncode != 0:
        raise RuntimeError(
            f"generation failed: {stderr.decode('utf-8', errors='replace')[-500:]}"
        )
    return stdout.decode("utf-8", errors="replace").strip()
