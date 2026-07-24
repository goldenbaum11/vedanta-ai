# Technology stack

Everything runs **local-first**: no cloud LLM APIs, no external data
services. The only machine that matters is the one this repo runs on
(currently an Apple M4 Max, 128 GB). The stack is organised into three
planes that exchange **files, not code** — each can be understood,
replaced, or moved to another machine independently.

```
Serving plane  (24/7)   ← what students talk to
Data plane     (admin)  ← transcripts → reviewed training data
Training plane (rare)   ← dataset → LoRA adapter → model file
```

---

## Serving plane

### Frontend

| Technology | Version | Role |
|---|---|---|
| [Next.js](https://nextjs.org) | 15 (App Router) | React framework; `output: "standalone"` for slim Docker images |
| [React](https://react.dev) | 19 | Functional components only (project convention) |
| [TypeScript](https://www.typescriptlang.org) | 5.6, strict mode | All frontend code |
| [Tailwind CSS](https://tailwindcss.com) | 3.4 | Styling; no component library |

No state-management library — auth and chat state live in
`localStorage` + small pub/sub helpers (`frontend/lib/auth.ts`).
Streaming chat uses the browser's native `ReadableStream` over
ndjson; no websocket layer.

Pages: `/` (chat with thread sidebar), `/admin` (persona pipeline
console), `/dashboard`.

### Backend

| Technology | Version | Role |
|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com) | 0.115+ | Async HTTP API; all I/O is `async/await` |
| [Uvicorn](https://www.uvicorn.org) | 0.32+ | ASGI server |
| [Pydantic](https://docs.pydantic.dev) v2 + pydantic-settings | 2.8+ | Request/response schemas; `.env`-driven config |
| [httpx](https://www.python-httpx.org) | 0.27+ | Async client for LLM/embedding/SHP calls |
| [SQLAlchemy Core](https://docs.sqlalchemy.org) (async) | 2.0 | Driver-agnostic SQL: `aiosqlite` in dev, `asyncpg` in prod — same code path |
| [ChromaDB](https://www.trychroma.com) | 0.5+ | Vector store; embedded `PersistentClient` in dev, HTTP server in Docker |
| [slowapi](https://slowapi.readthedocs.io) | 0.1.9+ | Rate limiting (per-user when authenticated, per-IP otherwise) |
| python-jose + bcrypt | — | HS256 JWTs; bcrypt used directly (passlib avoided deliberately) |
| pypdf | 5.x | PDF corpus ingestion |

Architecture inside the backend: an **intent classifier** (keyword
rules + Devanagari detection + LLM fallback) routes each query
through a **dispatcher** to one of the agent modules
(`vedic_scholar`, `sanskrit_grammar`, `communication`, `survival`,
`media`). Agents never call each other. Knowledge queries do RAG
retrieval **before** LLM inference; retrieval is hybrid (metadata
pinning for explicit verse refs like "BG 2.47" + semantic search).

**No LangChain / LangGraph** — evaluated and declined; see
`docs/adr/0001-no-langchain.md`.

### Model runtime (inference)

| Technology | Role |
|---|---|
| [LM Studio](https://lmstudio.ai) | Primary local LLM server (OpenAI-compatible API); currently serves Qwen 2.5 14B |
| [Ollama](https://ollama.com) | Alternative runtime; same code path via `llm_client.py` |
| `nomic-embed-text-v1.5` | Multilingual embeddings (Sanskrit/Devanagari-capable), served by LM Studio |

All LLM traffic goes through `backend/models/llm_client.py` — one
protocol, two interchangeable providers, selected by `LLM_PROVIDER`.

### Data stores

| Store | Dev | Prod (Docker) | Holds |
|---|---|---|---|
| Relational | SQLite (`vedanta.db`) | PostgreSQL 16 | users, messages/threads, audit logs, persona pipeline tables |
| Vector | Chroma embedded (`data/chroma/`) | Chroma server container | `vedic_texts` (verses + Vishva Vidya catalog), `communications`, `survival_knowledge`, `media_index` |
| Files | `data/` on disk | named Docker volumes | corpora (JSONL), transcripts, datasets, LoRA adapters |

### Optional integration

| Technology | Role |
|---|---|
| [Sanskrit Heritage Platform](https://sanskrit.inria.fr) (Inria) | Deterministic Sanskrit morphological parsing, prepended to the `sanskrit_grammar` agent's LLM context; off by default |

---

## Data plane (persona pipeline, `/admin`)

| Technology | Role |
|---|---|
| FastAPI background tasks (asyncio) | Job runner — extraction/training jobs with logs persisted per-line to the DB, polled by the UI. Deliberately no Celery/Redis: single-admin, single-box workflow |
| Local LLM (via `llm_client.py`) | Q&A pair mining from transcripts — extraction only, never rewriting, so the teacher's literal words are preserved |
| Postgres/SQLite tables | `persona_transcripts`, `persona_pairs` (review states), `persona_jobs` (logs), `persona_models` (registry) |

Privacy: everything under `data/persona/` is gitignored; student
names are scrubbed from pairs deterministically.

## Training plane (`training/`, separate venv)

| Technology | Version | Role |
|---|---|---|
| [MLX](https://github.com/ml-explore/mlx) + [mlx-lm](https://github.com/ml-explore/mlx-lm) | 0.32 / 0.31 | LoRA fine-tuning on Apple Silicon — chosen over PyTorch+CUDA because the training box *is* the Mac |
| Base model | `mlx-community/Qwen2.5-7B-Instruct-4bit` | Qwen chosen for multilingual strength (EN + PT + Sanskrit terms) |
| Hugging Face Hub | — | Base-model downloads only (cached); nothing is uploaded |

Deliverable: a LoRA adapter in `data/persona/adapters/<name>/`,
optionally fused (`mlx_lm fuse`) and loaded into LM Studio for
serving. PyTorch appears nowhere; the backend never imports any of
this.

---

## Infrastructure & operations

| Technology | Role |
|---|---|
| Docker Compose | Prod-ish stack: Postgres 16-alpine, Chroma server, backend (python:3.12-slim, multi-stage, non-root), frontend (node:20-alpine, standalone) |
| `.env` / python-dotenv | All configuration; no hardcoded secrets |
| JWT + role column | Auth: `student` default, `admin` unlocks `/admin` (promote via `scripts/make_admin.py`) |
| Encrypted audit log | Every PII-touching endpoint writes to `audit_logs` |

## Testing & tooling

| Technology | Role |
|---|---|
| pytest + pytest-asyncio | 86-test suite: unit (chunker, classifier, retriever, clients) + integration (auth, threads, agents) via FastAPI `TestClient` |
| respx / pytest-httpx | HTTP mocking for LLM/embedding calls — tests run without any model server |
| ruff | Linting + formatting (Python) |
| TypeScript strict + `next build` | Frontend type safety |

## Deliberately not used

| Technology | Why not |
|---|---|
| OpenAI / Anthropic / any cloud LLM | Privacy: ashram data never leaves local infrastructure (hard project rule) |
| LangChain / LangGraph | Abstraction cost exceeds benefit at this scale — ADR-001 |
| PyTorch / TensorFlow in the backend | Training is isolated in `training/` (MLX); serving consumes model files, not frameworks |
| Celery / Redis | In-process asyncio jobs suffice for a single-admin box |
| passlib | Broken with bcrypt 5.x; bcrypt is called directly |
