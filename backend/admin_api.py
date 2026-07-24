"""Admin API: the persona data pipeline.

All routes require the `admin` role (JWT). Flow:

1. POST   /api/v1/admin/transcripts          — upload transcript text,
                                               starts an extraction job
2. GET    /api/v1/admin/jobs/{id}            — poll status + live log
3. GET    /api/v1/admin/pairs?status=pending — review queue
4. PATCH  /api/v1/admin/pairs/{id}           — approve / reject / edit
5. GET    /api/v1/admin/dataset/stats        — progress toward target
6. POST   /api/v1/admin/dataset/export       — write train/valid JSONL
7. POST   /api/v1/admin/training/start       — LoRA training job (logs
                                               stream into the job row)
8. GET    /api/v1/admin/models               — model registry
9. POST   /api/v1/admin/models/{id}/test     — generate with an adapter

Uploads are JSON (filename + content) rather than multipart so we
don't need python-multipart; transcripts are plain text and small.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .persona import extraction, jobs, store
from .security import audit_log
from .security.auth import AuthenticatedUser, current_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "persona" / "raw"


# --- Schemas ---------------------------------------------------------------


class TranscriptUpload(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    target_speaker: str | None = None


class PairUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(pending|approved|rejected)$")
    question: str | None = None
    answer: str | None = None


class TrainingStart(BaseModel):
    model_name: str | None = Field(
        default=None, max_length=128, pattern=r"^[A-Za-z0-9._\-]+$"
    )


class ModelTest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    max_tokens: int = Field(default=400, ge=16, le=2000)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._ \-]", "_", base).strip() or "transcript.txt"
    if not cleaned.endswith(".txt"):
        cleaned += ".txt"
    return cleaned


# --- Transcripts + extraction ------------------------------------------------


@router.post("/transcripts")
async def upload_transcript(
    req: TranscriptUpload,
    admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    settings = get_settings()
    target = (req.target_speaker or settings.persona_target_speaker).strip()

    speakers = extraction.list_speakers(req.content)
    if target not in speakers:
        found = ", ".join(speakers) or "(none — is this a speaker-labelled transcript?)"
        raise HTTPException(
            status_code=422,
            detail=f"speaker {target!r} not found in transcript. Speakers present: {found}",
        )

    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(req.filename)
    path = _RAW_DIR / filename
    # Avoid clobbering an earlier upload of the same name.
    counter = 1
    while path.exists():
        path = _RAW_DIR / f"{Path(filename).stem}_{counter}.txt"
        counter += 1
    path.write_text(req.content, encoding="utf-8")

    transcript_id = await store.create_transcript(
        filename=path.name,
        uploaded_by=admin.subject,
        content_path=str(path),
        target_speaker=target,
        word_count=len(req.content.split()),
    )
    job_id = await jobs.start_extraction(transcript_id)
    await audit_log.record(
        endpoint="/api/v1/admin/transcripts",
        method="POST",
        user_id=admin.subject,
        status_code=201,
        detail=f"transcript={transcript_id} file={path.name} job={job_id}",
    )
    return {"transcript_id": transcript_id, "job_id": job_id, "speakers": speakers}


@router.get("/transcripts")
async def list_transcripts(
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    return {"transcripts": await store.list_transcripts()}


# --- Jobs --------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    return {"jobs": await store.list_jobs()}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: int,
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


# --- Pairs review --------------------------------------------------------------


@router.get("/pairs")
async def list_pairs(
    status: str | None = None,
    transcript_id: int | None = None,
    limit: int = 200,
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    if limit <= 0 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be in (0, 1000]")
    pairs = await store.list_pairs(
        status=status, transcript_id=transcript_id, limit=limit
    )
    return {"pairs": pairs}


@router.patch("/pairs/{pair_id}")
async def update_pair(
    pair_id: int,
    req: PairUpdate,
    admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    pair = await store.get_pair(pair_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="pair not found")
    updated = await store.update_pair(
        pair_id, status=req.status, question=req.question, answer=req.answer
    )
    if req.status:
        await audit_log.record(
            endpoint=f"/api/v1/admin/pairs/{pair_id}",
            method="PATCH",
            user_id=admin.subject,
            status_code=200,
            detail=f"pair={pair_id} status={req.status}",
        )
    return updated or {}


# --- Dataset ------------------------------------------------------------------


@router.get("/dataset/stats")
async def dataset_stats(
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    return await store.dataset_stats()


@router.post("/dataset/export")
async def export_dataset(
    admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    try:
        result = await jobs.export_dataset()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_log.record(
        endpoint="/api/v1/admin/dataset/export",
        method="POST",
        user_id=admin.subject,
        status_code=200,
        detail=f"train={result['train']} valid={result['valid']}",
    )
    return result


# --- Training + models ----------------------------------------------------------


@router.post("/training/start")
async def start_training(
    req: TrainingStart,
    admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    try:
        job_id = await jobs.start_training(req.model_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit_log.record(
        endpoint="/api/v1/admin/training/start",
        method="POST",
        user_id=admin.subject,
        status_code=202,
        detail=f"job={job_id} model={req.model_name or '(auto)'}",
    )
    return {"job_id": job_id}


@router.get("/models")
async def list_models(
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    return {"models": await store.list_models()}


@router.post("/models/{model_id}/test")
async def test_model(
    model_id: int,
    req: ModelTest,
    _admin: AuthenticatedUser = Depends(current_admin),
) -> dict[str, object]:
    try:
        answer = await jobs.test_model(model_id, req.prompt, max_tokens=req.max_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"answer": answer}
