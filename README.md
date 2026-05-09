# Vedanta AI

Local-first multi-agent AI for an ashram community. Five domains: Vedic
text translation, student communication, infosec, survival skills, media.

> **Phase 2 — Vedic Text Intelligence.** Multilingual embeddings via a
> local `/v1/embeddings` server (LM Studio's `nomic-embed-text-v1.5`),
> verse-aware Sanskrit chunking, hybrid (metadata-pinned + semantic) RAG
> retrieval, ndjson token streaming, and per-browser conversation
> history with persistent citations. ~2,100-chunk corpus covering the
> full Bhagavad Gita (701 verses + 700 Sivananda commentaries), 10
> Principal Upanishads, and one PDF-extracted commentary. See
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

| Method | Path                       | Purpose                                       |
|--------|----------------------------|-----------------------------------------------|
| GET    | `/health`                  | Provider / embeddings / Chroma / DB probes + collection counts |
| GET    | `/api/v1/agents`           | List of agent labels                          |
| POST   | `/api/v1/chat`             | Classify → dispatch → persist (one JSON response) |
| POST   | `/api/v1/chat/stream`      | Same, but ndjson stream: `intent` → `meta` → `token`* → `done`/`error` |
| GET    | `/api/v1/messages`         | Recent exchanges (filter by `?user_id=`)      |

The frontend uses `/chat/stream` so users see citations within ~1s and
tokens within ~5s, instead of a 25-second blocking wait.

## RAG corpus

The `vedic_texts` collection is the canonical source for `vedic_scholar`
and `sanskrit_grammar`. Default ingest produces ~2,100 chunks:

| File                                              | Source                                                                      | Chunks | Layers                       |
|---------------------------------------------------|-----------------------------------------------------------------------------|-------:|------------------------------|
| `bhagavad_gita.jsonl`                             | [ravisiyer/gita-data](https://github.com/ravisiyer/gita-data) (Unlicense)   |  1,401 | Sanskrit + IAST + Gambirananda translation + Sivananda commentary |
| `bhagavad_gita_commentary_supplement.jsonl`       | hand-paraphrased Shankara / Ramanuja perspectives                            |      5 | English commentary           |
| `upanishads.jsonl`                                | [atmabodha/Vedanta_Datasets](https://github.com/atmabodha/Vedanta_Datasets) (ML grant) + [hrgupta/indian-scriptures](https://github.com/hrgupta/indian-scriptures) (MIT) | 582 | Sanskrit + (partial) English for 10 Principal Upanishads |
| `aurobindo_isha_upanishad_1945.pdf`               | Internet Archive — Aurobindo's Isha commentary (1945, public domain in India)|    121 | English prose (PDF-extracted) |

Reproducible fetch:

```bash
python3 scripts/fetch_gita.py          # writes data/vedic_texts/bhagavad_gita.jsonl
python3 scripts/fetch_upanishads.py    # writes data/vedic_texts/upanishads.jsonl
python3 scripts/fetch_pdfs.py          # downloads commentary PDFs from Internet Archive
python3 scripts/ingest_corpus.py --collection vedic_texts --dir data/vedic_texts/
```

JSONL corpora are committed to the repo (small, ours by transformation).
PDFs are *not* committed (heavy + jurisdictionally ambiguous on US
copyright); `fetch_pdfs.py` reproduces them on demand.

Ingest is idempotent: re-running skips chunks already in the collection
(by `chunk_id`), so partial runs are safe to resume. Use `--reset` only
when changing `EMBEDDING_PROVIDER` (different providers produce different
vector dimensions).

Supported formats (auto-detected by file extension):

| Extension | Chunker            | Best for                                        |
|-----------|--------------------|-------------------------------------------------|
| `.jsonl`  | verse-aware        | sacred texts, one verse per line (preferred)    |
| `.md`     | structured-text    | `## Chapter X` / `### Verse Y` markdown         |
| `.txt`    | paragraph          | prose                                           |
| `.pdf`    | paragraph (pypdf)  | commentary PDFs                                 |

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

**Known gaps in the Upanishad corpus** (TODO in a future expansion):
- Chandogya Upanishad — not present in the upstream sources we use.
- Kena, Mundaka, Brihadaranyaka, Prashna, Aitareya, Taittiriya,
  Shvetashvatara — Sanskrit text only; English translations pending.
  The agent's anti-fabrication guard will refuse to invent translations
  for these until they're added.

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
