# Vedanta AI

Local-first multi-agent AI system for an ashram community. Five domains:
Vedic text translation, student communication, infrastructure security,
survival/practical knowledge, and media processing.

> **Status:** Phase 1 — Foundation (FastAPI + Ollama + intent router +
> Next.js chat UI + SQLite + ChromaDB). Agents return stub responses until
> their domain phase is implemented. See
> [`vedanta_ai_cursor_prompt.md`](./vedanta_ai_cursor_prompt.md) for the
> full multi-phase spec.

## Architecture

```
User ─▶ Next.js chat UI ─▶ FastAPI /api/v1/chat
                                  │
                          Intent classifier
                                  │
                          Dispatcher  ─▶  Agent (Vedic / Sanskrit /
                                          Communication / InfoSec /
                                          Survival / Media)
                                  │
                          ┌───────┼────────┐
                          ▼       ▼        ▼
                       SQLite   ChromaDB  Ollama
                       (state)  (RAG)     (LLM, local)
```

## Prerequisites

- macOS / Linux
- **Python 3.9+** (3.11+ recommended; 3.9 supported via `eval_type_backport`)
- **Node.js 20+**
- **[Ollama](https://ollama.com)** running locally
- (Phase 6) FFmpeg + Tesseract installed system-wide

## Quickstart

### 1. Install Ollama and pull a model

```bash
brew install ollama
brew services start ollama         # or run `ollama serve` in a separate terminal
ollama pull llama3                 # ~4.7 GB. Smaller alt: `ollama pull llama3.2:3b`
```

Sanity check: `curl http://localhost:11434/api/tags` should return JSON.

### 2. Configure environment

```bash
cp .env.example .env
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
```

If you pulled a model other than `llama3`, set `OLLAMA_DEFAULT_MODEL` in `.env`.

### 3. Backend

Run from the **project root** (package-relative imports require it):

```bash
python3 -m pip install --user -r backend/requirements.txt
python3 -m uvicorn backend.main:app --reload --port 8000
```

- Health: <http://localhost:8000/health>
- OpenAPI docs: <http://localhost:8000/docs>

> Using a venv is cleaner if your Python install supports it:
> `python3 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt`.

### 4. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>.

### 5. Smoke test

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Translate Bhagavad Gita 2.47 with three layers of meaning"}' \
  | python3 -m json.tool
```

`/health` should show `ollama.reachable: true` and `chroma.reachable: true`.
The chat call should route to `vedic_scholar` and return a real LLM response.

## API surface (Phase 1)

| Method | Path                  | Purpose                                          |
|--------|-----------------------|--------------------------------------------------|
| GET    | `/health`             | Liveness + Ollama / Chroma / DB probes           |
| GET    | `/api/v1/agents`      | List of supported agent labels                   |
| POST   | `/api/v1/chat`        | Classify, dispatch to agent, persist, return     |
| GET    | `/api/v1/messages`    | Recent message exchanges (admin view)            |

`POST /api/v1/chat` accepts an optional `agent_override` to bypass the
classifier — useful for testing each agent in isolation.

## (Phase 2+) Ingest a corpus

Place text/markdown files under `data/vedic_texts/`, then:

```bash
python3 scripts/ingest_corpus.py \
  --collection vedic_texts \
  --dir data/vedic_texts/
```

Phase 1 supports plain-text and markdown. PDF + verse-aware Sanskrit
chunking arrives in Phase 2.

## Repository layout

```
vedanta-ai/
├── backend/        FastAPI server, agents, RAG, security
├── frontend/       Next.js + Tailwind chat UI
├── data/           Source corpora + ChromaDB persistence
├── scripts/        One-off operational scripts
├── .cursorrules    AI coding-assistant guardrails
└── .env.example    Configuration template
```

## Development conventions

- All LLM calls go through `backend/models/llm_client.py`.
- Each agent exposes `async def handle(query: str, context: dict) -> AgentResponse`.
- Agents never call each other — routing is the dispatcher's job.
- Every endpoint that touches PII writes to the `audit_logs` table.
- See [`.cursorrules`](./.cursorrules) for the full house style.

## Troubleshooting

- **`zsh: command not found: python3.11`** — use `python3` instead. Any
  3.9+ works; the backport package handles 3.9 union-syntax for pydantic.
- **`ollama.reachable: false`** in `/health` — start the daemon:
  `brew services start ollama` or `ollama serve` in another terminal.
- **`pyexpat` ImportError on Homebrew Python** — your Homebrew Python and
  `expat` got out of sync. Fix with `brew reinstall expat python@3.12`,
  or fall back to the system `python3`.
- **CORS errors from the frontend** — confirm `CORS_ORIGINS` in `.env`
  contains `http://localhost:3000` (default).

## License

Internal / unreleased.
