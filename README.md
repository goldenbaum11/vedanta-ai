# Vedanta AI

Local-first multi-agent AI for an ashram community. Five domains: Vedic
text translation, student communication, infosec, survival skills, media.

> **Phase 3 — Communication & Multi-turn Memory.** All Phase 2 features
> plus: per-thread multi-turn memory (the LLM sees the prior six
> exchanges every reply), a thread sidebar in the UI with auto-titles,
> a strengthened communication agent with FAQ-grounded RAG and a
> conservative escalation detector (distress short-circuits the LLM
> entirely and returns a fixed compassionate reply with crisis hotlines),
> and an opt-in deterministic Sanskrit grammar parser via the Sanskrit
> Heritage Platform (graceful fall-back to LLM-only when disabled or
> unavailable). 86-test pytest suite gates the backend. See
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
| POST   | `/api/v1/chat`             | Classify → dispatch → persist (one JSON response). Accepts `thread_id` (optional); response always echoes the assigned id. |
| POST   | `/api/v1/chat/stream`      | Same, but ndjson stream: `intent` → `meta` → `token`* → `done`/`error`. Stream events carry `thread_id`. |
| GET    | `/api/v1/messages`         | Recent exchanges. Filter by `?user_id=` and/or `?thread_id=`; auth users are auto-scoped to their own `user:N`. |
| GET    | `/api/v1/threads`          | Per-user thread list with first-message titles, message counts, and last-active timestamps. |
| POST   | `/api/v1/auth/register`    | Create account, return JWT                     |
| POST   | `/api/v1/auth/login`       | Exchange credentials for a JWT                 |
| GET    | `/api/v1/auth/me`          | Current authenticated profile                  |

The frontend uses `/chat/stream` so users see citations within ~1s and
tokens within ~5s, instead of a 25-second blocking wait.

**Auth is optional.** Anonymous users still get full chat (rate limited
to `RATE_LIMIT_CHAT_ANONYMOUS`, default 30/minute by IP). Signing in
swaps the rate-limit key from `ip:...` to `user:N` and raises the
ceiling to `RATE_LIMIT_CHAT_AUTHENTICATED` (default 120/minute). All
auth endpoints share a tighter `RATE_LIMIT_AUTH` (default 10/minute).
Tokens are HS256 JWTs signed with `SECRET_KEY` and live for
`JWT_EXPIRE_MINUTES` (default 24 h). The frontend stores the token in
`localStorage` under `vedanta:auth` and attaches it to every request as
`Authorization: Bearer …`.

## Multi-turn conversations

Every chat call belongs to a `thread_id`. Omit it and the server
mints a fresh one (`thread_<24-hex>`); echo it back on subsequent
turns and the dispatcher feeds the prior six exchanges (twelve
messages — capped to keep small local models fast) into the LLM as
ordered `system → user → assistant → … → user` chat history.

Threads are persisted on the same `messages` table used elsewhere,
just with an additional `thread_id` column. `GET /api/v1/threads`
returns a per-user listing newest-first with the first message as a
title; the frontend renders this as a sidebar with a "+ New" button
that starts a fresh thread. Switching threads in the UI re-hydrates
its history from `GET /api/v1/messages?thread_id=...`.

## Communication agent

The `communication` agent answers visitor / student messages on
behalf of the ashram. It now does three things before any LLM call:

1. **Escalation classification** — keyword/phrase patterns flag
   *distress* (suicidal ideation, harassment, abuse), *personal
   guidance* (initiation, divorce, life decisions), and
   *professional referral* (medical / legal / financial). Distress
   short-circuits the LLM entirely and returns a fixed compassionate
   reply that includes Indian crisis hotlines (iCall, Vandrevala).
2. **RAG grounding** — semantic retrieval over the `communications`
   collection (`data/communications/ashram_faq.jsonl` ships 19
   curated chunks: visiting hours, daily schedule, donations, safe-
   guarding policy, contacts, etc.). Hits are passed to the LLM as
   a numbered "Ashram knowledge base" block.
3. **Strong system prompt** — refuses theological claims, refuses
   to invent Sanskrit verses, refuses worldly outcomes ("this will
   heal you"), and always tags the reply with a `[classification:
   <label>]` line so a future review queue can filter on it.

Every reply persists with an `escalate` flag on the messages row,
which downstream review tooling can use to prioritise human review.

```bash
python3 scripts/ingest_corpus.py \
    --collection communications \
    --dir data/communications/ \
    --format jsonl
```

## Sanskrit grammar (deterministic parser)

The `sanskrit_grammar` agent can call the **Sanskrit Heritage
Platform** (Inria) before the LLM to get a deterministic
morphological breakdown (sandhi splits, root forms, case endings)
that the LLM then explains in natural language. This is **opt-in**:

```env
SANSKRIT_HERITAGE_ENABLED=true
SANSKRIT_HERITAGE_BASE_URL=https://sanskrit.inria.fr/cgi-bin/SKT/sktreader.cgi
```

When disabled (default) or unavailable (timeout / 5xx), the agent
gracefully falls back to LLM-only analysis and the
`structural_parser_used` field on the response metadata records
the outcome. The integration is intentionally network-tolerant so
running offline never breaks the chat path. For production we
recommend a self-hosted Docker SHP image; the public Inria server
is fine for development.

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

## Tests

The backend ships with an offline-friendly pytest suite covering
chunker, classifier, retriever, dispatcher, LLM / embedding
clients, database, auth, rate-limiting, multi-turn threading,
communication-agent escalation, and the Sanskrit Heritage parser.
All HTTP traffic is mocked with `respx` and ChromaDB runs
in-memory, so the suite is fully hermetic.

```bash
python3 -m pip install --user pytest pytest-asyncio respx pytest-httpx
python3 -m pytest -q
```

Expect ~5–8 seconds for 86 tests on a warm machine (the agent
end-to-end tests dominate the wall-clock).

## Layout

```
backend/    FastAPI server, agents, RAG, grammar, security (auth + rate-limit)
frontend/   Next.js + Tailwind chat UI (with thread sidebar + auth bar)
data/       Source corpora + ChromaDB persistence
docs/adr/   Architecture decision records
scripts/    One-off operational scripts
tests/      Offline pytest suite (mocks + in-memory chroma)
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
