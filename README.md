# Vedanta AI

Local-first multi-agent AI for an ashram community. Five domains: Vedic
text translation, student communication, infosec, survival skills, media.

> **Phase 2 — Vedic Text Intelligence.** Multilingual embeddings via a
> local `/v1/embeddings` server (LM Studio's `nomic-embed-text-v1.5`),
> verse-aware Sanskrit chunking, and hybrid (metadata-pinned + semantic)
> RAG retrieval wired into `vedic_scholar` and `sanskrit_grammar`. See
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

## API

| Method | Path                | Purpose                                       |
|--------|---------------------|-----------------------------------------------|
| GET    | `/health`           | Provider / embeddings / Chroma / DB probes + collection counts |
| GET    | `/api/v1/agents`    | List of agent labels                          |
| POST   | `/api/v1/chat`      | Classify → dispatch → persist (`agent_override` to bypass) |
| GET    | `/api/v1/messages`  | Recent exchanges                              |

## RAG corpus

The `vedic_texts` collection is the canonical source for `vedic_scholar`
and `sanskrit_grammar`. A starter Bhagavad Gita seed dataset (BG 1.1,
2.47, 2.48, 4.7, 4.8, 9.22, 18.66 + Shankara/Ramanuja commentary
glosses) ships in `data/vedic_texts/bhagavad_gita_seed.jsonl`.

```bash
# Reset + ingest. --reset is required when changing EMBEDDING_PROVIDER
# (different providers produce different vector dimensions).
python3 scripts/ingest_corpus.py \
  --collection vedic_texts \
  --dir data/vedic_texts/ \
  --reset
```

Supported formats (auto-detected by file extension):

| Extension | Chunker            | Best for                                        |
|-----------|--------------------|-------------------------------------------------|
| `.jsonl`  | verse-aware        | sacred texts, one verse per line (preferred)    |
| `.md`     | structured-text    | `## Chapter X` / `### Verse Y` markdown         |
| `.txt`    | paragraph          | prose                                           |
| `.pdf`    | paragraph (pypdf)  | commentary PDFs (`pip install pypdf`)           |

Embedding provider is configured in `.env`:

```env
EMBEDDING_PROVIDER=openai_compatible      # or "ollama" or "default"
EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
EMBEDDING_BASE_URL=                        # empty -> reuse LLM URL
```

Hybrid retrieval is automatic: when a query mentions a verse like
"BG 2.47", that verse is pinned via metadata filter *before* semantic
search, ensuring the requested verse is always present in the LLM's
context. Out-of-corpus verses cause the agent to refuse rather than
fabricate Sanskrit.

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
