# Vedanta AI

Local-first multi-agent AI for an ashram community. Five domains: Vedic
text translation, student communication, infosec, survival skills, media.

> **Phase 1 — Foundation.** FastAPI + intent router + 6 agent stubs +
> Next.js chat UI + SQLite + ChromaDB. See
> [`vedanta_ai_cursor_prompt.md`](./vedanta_ai_cursor_prompt.md) for the
> full multi-phase spec.

## Architecture

```
UI ─▶ FastAPI /api/v1/chat ─▶ Classifier ─▶ Dispatcher ─▶ Agent
                                                    │
                                       SQLite · ChromaDB · LLM (local)
```

## Prerequisites

- Python 3.9+ (3.11+ recommended; 3.9 supported via `eval_type_backport`)
- Node.js 20+
- A local LLM: **[Ollama](https://ollama.com)** *or* any OpenAI-compatible
  server (LM Studio, llama.cpp, vLLM, Jan)

## Quickstart

### 1. Configure

```bash
cp .env.example .env
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
```

### 2. Start a local LLM (pick one)

**Ollama (default)** — set `LLM_PROVIDER=ollama` in `.env`:

```bash
brew install ollama && brew services start ollama
ollama pull llama3            # or llama3.2:3b
```

**LM Studio (recommended on macOS 26 + Apple Silicon)** — set
`LLM_PROVIDER=openai_compatible` in `.env`, install via
`brew install --cask lm-studio`, open the app, load a model, and start
**Developer → Local Server** (port 1234). Leave
`OPENAI_COMPATIBLE_MODEL=` empty to auto-pick whatever's loaded.

### 3. Backend (run from project root)

```bash
python3 -m pip install --user -r backend/requirements.txt
python3 -m uvicorn backend.main:app --reload --port 8000
```

Health: <http://localhost:8000/health> · Docs: <http://localhost:8000/docs>

### 4. Frontend

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>.

### 5. Smoke test

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
curl -s -X POST http://127.0.0.1:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Translate Bhagavad Gita 2.47"}' | python3 -m json.tool
```

`/health` should show `llm.reachable: true`. The chat call should route
to `vedic_scholar` and return a real translation.

## API (Phase 1)

| Method | Path                | Purpose                                       |
|--------|---------------------|-----------------------------------------------|
| GET    | `/health`           | Provider / Chroma / DB probes                 |
| GET    | `/api/v1/agents`    | List of agent labels                          |
| POST   | `/api/v1/chat`      | Classify → dispatch → persist (`agent_override` to bypass) |
| GET    | `/api/v1/messages`  | Recent exchanges                              |

## (Phase 2+) Ingest a corpus

```bash
python3 scripts/ingest_corpus.py --collection vedic_texts --dir data/vedic_texts/
```

Plain-text/markdown only in Phase 1. PDF + verse-aware Sanskrit chunking
arrives in Phase 2.

## Layout

```
backend/    FastAPI server, agents, RAG, security
frontend/   Next.js + Tailwind chat UI
data/       Source corpora + ChromaDB persistence
scripts/    One-off operational scripts
```

## Conventions

- All LLM calls go through `backend/models/llm_client.py`.
- Each agent exposes `async def handle(query, context) -> AgentResponse`.
- Agents never call each other — routing is the dispatcher's job.
- Every endpoint that touches PII writes to `audit_logs`.
- Full house style in [`.cursorrules`](./.cursorrules).

## Troubleshooting

- **`llm.reachable: false`** — start the configured provider
  (`brew services start ollama` or LM Studio's local server).
- **Ollama 0.23.2 hangs / times out on macOS 26 + Apple Silicon** — known
  GPU-discovery regression (CPU fallback is unusable). Switch to LM Studio
  per step 2 above, or install the official Ollama `.dmg`.
- **`pyexpat` ImportError on Homebrew Python** — `brew reinstall expat
  python@3.12`, or fall back to the system `python3`.
- **`zsh: command not found: python3.11`** — just use `python3`; the
  backport handles 3.9 union syntax for pydantic.

## License

Internal / unreleased.
