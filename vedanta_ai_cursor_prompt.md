# Vedanta AI — Cursor Development Prompt

## Project Overview

Build **Vedanta AI**, a modular, local-first multi-agent AI system for an ashram
community. The system handles five domains: Vedic text translation, student
communication, infrastructure security, survival/practical knowledge, and
media processing.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Next.js, Tailwind CSS |
| Backend | Python 3.11, FastAPI |
| Local LLM | Ollama (primary), LM Studio (fallback) |
| Database | SQLite (dev) → PostgreSQL (prod) |
| Vector DB | ChromaDB |
| Media | Whisper (transcription), FFmpeg, Tesseract OCR |
| Security | AES encryption, audit logging, automated backups |

---

## Repository Structure

```
vedanta-ai/
├── backend/
│   ├── main.py                   # FastAPI entrypoint
│   ├── router/
│   │   ├── intent_classifier.py  # Classifies incoming queries to route to agent
│   │   └── dispatcher.py         # Routes to correct agent
│   ├── agents/
│   │   ├── vedic_scholar.py      # Module 1: Vedic text translation
│   │   ├── sanskrit_grammar.py   # Module 1b: Grammar analysis
│   │   ├── communication.py      # Module 2: Student/public DMs
│   │   ├── infosec_guardian.py   # Module 3: Security monitoring
│   │   ├── survival_skills.py    # Module 4: Off-grid practical knowledge
│   │   └── media_engine.py       # Module 5: Video/image processing
│   ├── rag/
│   │   ├── embeddings.py         # Embedding pipeline
│   │   ├── vector_store.py       # ChromaDB interface
│   │   └── retriever.py          # RAG query logic
│   ├── knowledge/
│   │   ├── ingest.py             # Ingest PDFs, texts into vector DB
│   │   └── partitions.py         # Separate corpora per domain
│   ├── security/
│   │   ├── audit_log.py
│   │   ├── encryption.py
│   │   └── monitoring.py
│   └── models/
│       └── llm_client.py         # Unified interface to Ollama/LM Studio
├── frontend/
│   ├── app/
│   │   ├── page.tsx              # Main chat UI
│   │   ├── dashboard/page.tsx    # Admin dashboard
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── AgentSelector.tsx
│   │   └── TranslationCard.tsx
│   └── lib/
│       └── api.ts                # API client
├── data/
│   ├── vedic_texts/              # Sanskrit source texts, PDFs
│   ├── survival_knowledge/       # Off-grid, medicine, agriculture docs
│   └── media/                    # Audio, video, images for processing
├── scripts/
│   └── ingest_corpus.py          # One-time corpus ingestion runner
├── .cursorrules                  # Cursor AI instructions (see below)
├── .env.example
└── README.md
```

---

## Phase 1 — Foundation (Start Here)

Build the core infrastructure first. No agents yet.

### Tasks

1. **FastAPI server** with health check endpoint (`GET /health`)
2. **Ollama client** wrapper in `llm_client.py`  
   - Default model: `llama3` or `mistral`
   - Method: `async def complete(system_prompt: str, user_message: str) -> str`
3. **Intent classifier** — takes a user message, returns one of:
   `["vedic_scholar", "sanskrit_grammar", "communication", "infosec", "survival", "media"]`
4. **ChromaDB setup** with named collections per domain:
   - `vedic_texts`, `survival_knowledge`, `communications`, `media_index`
5. **Basic Next.js chat UI** — text input, message history, agent label on each response
6. **SQLite database** with tables: `messages`, `audit_log`, `users`

### Deliverable: working chat that routes a message to a named agent and returns a stub response.

---

## Phase 2 — Vedic Text Intelligence

### Module 1: Vedic Scholar Agent

**System prompt for this agent:**

```
You are a Vedic scholar agent within the Vedanta AI system.

Your responsibilities:
- Translate Sanskrit verses from the Vedas, Upanishads, Puranas, Bhagavad Gita,
  and related texts with high fidelity.
- Always cite the source: text name, chapter (adhyaya), and verse number (shloka).
- For every translation, provide three layers:
    1. Word-for-word gloss (anvaya)
    2. Literal translation
    3. Meaning in context (bhava)
- Provide multiple commentary perspectives when philosophically significant:
  Advaita (Shankaracharya), Vishishtadvaita (Ramanujacharya), Dvaita (Madhvacharya).
  Attribute each view clearly.
- Preferred reference scholars: Swami Gambhirananda, Swami Sivananda,
  Swami Vivekananda, Sri Aurobindo, A.C. Bhaktivedanta Swami (Vaishnava texts).
- Never invent verses, verse numbers, or commentaries. If uncertain, say so
  explicitly and recommend a physical source.
- Respond in the language the user writes in (English, Sanskrit, Hindi).
```

**Module 1b: Sanskrit Grammar Agent**

```
You are a Sanskrit grammar analysis agent.

Your responsibilities:
- Parse Sanskrit verses: identify sandhi (phonetic junctions), samasa (compound
  words), vibhakti (case endings), dhatu (verb roots), pratyaya (suffixes),
  and chandas (meter).
- Produce a structured grammatical breakdown of each word in a verse.
- Explain grammatical rules in accessible language for students learning Sanskrit.
- Use standard Devanagari notation and IAST transliteration side-by-side.
- Reference Panini's Ashtadhyayi rules when relevant (cite the sutra number).
```

### RAG Corpus for Module 1

Ingest the following into the `vedic_texts` ChromaDB collection:
- All four Vedas (Rigveda, Samaveda, Yajurveda, Atharvaveda)
- 108 Upanishads (prioritize the principal 12)
- Bhagavad Gita with Shankaracharya and Ramanuja commentaries
- Brahma Sutras
- Major Puranas (18 Mahapuranas)
- Ramayana and Mahabharata

**Embedding strategy:** chunk by verse. Each chunk = one shloka + metadata
(source, chapter, verse, language: Sanskrit/transliteration/translation).

---

## Phase 3 — Communication Agent

### Module 2: Student and Public Communication

**System prompt for this agent:**

```
You are the communication agent for an ashram. You handle incoming messages
from students and the public.

Classification — always classify each message into one of:
  [spiritual_question] [event_inquiry] [donation_support]
  [personal_guidance] [logistical_admin] [distress_flag] [other]

Response rules:
- spiritual_question: Draft a warm, grounded response from the knowledge base.
  If the question is deep or personal, escalate to a human teacher with a note.
- logistical_admin: Answer from the ashram knowledge base only. If not found,
  say so and suggest direct contact.
- personal_guidance: Always escalate to a human teacher. Acknowledge warmly.
- distress_flag: IMMEDIATELY flag for human review. Do not attempt to handle.
  Respond only: "Thank you for reaching out. A teacher will be in touch with
  you personally and soon."

Tone: compassionate, clear, non-promotional, grounded in dharma.
Never make theological claims that could embarrass the institution.
Log every response with: timestamp, classification, confidence score, escalation flag.

Platform note: responses may be sent via Instagram DM, email, or web form.
Keep Instagram DM responses under 300 characters unless the question requires depth.
```

### Instagram DM Integration

- Use the Instagram Graph API (requires Facebook App + page token)
- Build a webhook endpoint: `POST /webhook/instagram`
- Flow: receive DM → classify → generate response → queue for human review
  → send after approval (do not auto-send without review in v1)
- Store all incoming/outgoing messages in the `communications` table

---

## Phase 4 — InfoSec Layer

### Module 3: InfoSec Guardian

**System prompt for this agent:**

```
You are the InfoSec Guardian for the Vedanta AI system. You protect the ashram's
digital infrastructure and personal data.

Responsibilities:
- Monitor access logs for anomalous patterns: repeated failed logins, unusual
  IP addresses accessing admin endpoints, off-hours access to PII data.
- Enforce data minimization: flag any process requesting more personal data
  than its task requires.
- Generate a weekly privacy summary: what was accessed, by whom, anomalies found.
- Alert immediately on: (a) login attempts > 5 in 10 minutes from one IP,
  (b) any new IP accessing /admin routes, (c) PII access outside 6am–10pm local.

Operating principle: when in doubt, restrict access rather than permit it.
Log all decisions with reasoning.
```

### Security implementation tasks

- AES-256 encryption for all PII at rest
- JWT authentication for admin routes
- Rate limiting on all public endpoints (10 req/min per IP)
- Automated daily backups to local encrypted storage
- Audit log table: every API call logged with user, endpoint, timestamp, IP

---

## Phase 5 — Survival Skills Knowledge Base

### Module 4: Survival and Practical Skills

**System prompt for this agent:**

```
You are a practical skills knowledge agent for the ashram community. You provide
grounded, reliable knowledge for resilient, self-sufficient living.

Knowledge domains:
- Traditional medicine, Ayurveda, plant remedies, first aid
- Construction, shelter, earthbuilding, natural materials
- Permaculture, food growing, seed saving, soil health
- Water sourcing, purification, rainwater harvesting
- Energy-independent living: solar, biogas, passive design
- Food preservation: fermentation, drying, canning, root cellaring
- Community resilience and dharmic self-sufficiency

Rules:
- Distinguish clearly between educational information and tasks requiring
  expert supervision. Always note when professional or medical help is needed.
- Prefer time-tested, low-technology solutions that work without grid power
  or internet connectivity.
- Connect practical knowledge to Vedic/dharmic context where natural:
  Ayurveda, Vastu Shastra, traditional agricultural knowledge (krishi).
- For medical topics: provide traditional context but state clearly that
  serious conditions require qualified medical attention.
```

---

## Phase 6 — Media Engine

### Module 5: Video and Image Intelligence

**System prompt for this agent:**

```
You are the media processing agent. You transcribe, extract, and index
content from video, audio, and image files.

Capabilities:
- Transcribe audio/video using Whisper. For Sanskrit or Hindi content,
  flag for Module 1 (Vedic Scholar) after transcription.
- Extract text from images of manuscripts, handwritten notes, printed books
  using OCR (Tesseract). Route extracted text to the appropriate agent.
- Tag and index all content with: topic, language, speaker (if known),
  text references (e.g. "Bhagavad Gita 2.47"), timestamp.
- Flag low-quality audio (SNR < threshold) or blurry images for re-submission.
- Never guess at unclear words in sacred texts — flag for human review.
```

---

## .cursorrules file

Create this file at the project root to guide Cursor's AI assistance:

```
# Vedanta AI — Cursor Rules

## Project context
This is a local-first, privacy-sensitive multi-agent AI system for an ashram.
All user data stays on local infrastructure. No data should be sent to
external APIs unless explicitly required (Instagram Graph API is the only exception).

## Code style
- Python: follow PEP 8, use async/await for all I/O, type hints on all functions
- TypeScript: strict mode, functional components only, no class components
- All API endpoints must be authenticated except /health and /webhook/instagram
- Every function that touches PII must write to the audit_log table

## Architecture rules
- Each agent is a separate Python module with a single async entry function:
  async def handle(query: str, context: dict) -> AgentResponse
- Agents do NOT call each other directly — all routing goes through dispatcher.py
- RAG retrieval must be called before LLM inference for all knowledge queries
- LLM calls go through llm_client.py only — never call Ollama directly

## Security rules
- Never log raw user messages to stdout/stderr — only to the encrypted audit_log
- All PII fields in database must be encrypted at rest
- No hardcoded secrets — use environment variables via python-dotenv

## Naming conventions
- Agent files: snake_case matching the intent classifier output labels
- API routes: /api/v1/{resource} pattern
- Database tables: snake_case, plural (messages, users, audit_logs)

## What NOT to do
- Do not use OpenAI, Anthropic, or any cloud LLM API — local Ollama only
- Do not store plaintext passwords
- Do not auto-send Instagram DMs without human review in v1
- Do not invent Sanskrit translations — always retrieve from the corpus first
```

---

## Environment Variables (.env.example)

```env
# LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=llama3

# Database
DATABASE_URL=sqlite:///./vedanta.db

# ChromaDB
CHROMA_PERSIST_DIR=./data/chroma

# Instagram (Phase 3)
INSTAGRAM_APP_ID=
INSTAGRAM_APP_SECRET=
INSTAGRAM_PAGE_TOKEN=
INSTAGRAM_VERIFY_TOKEN=

# Security
SECRET_KEY=                        # JWT signing key — generate with: openssl rand -hex 32
ENCRYPTION_KEY=                    # AES key — generate with: openssl rand -hex 32

# App
ADMIN_EMAIL=
LOCAL_TIMEZONE=Asia/Kolkata
```

---

## Getting Started Commands

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn chromadb ollama whisper pytesseract python-dotenv
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev

# Pull local LLM model
ollama pull llama3

# Ingest initial corpus (after placing texts in /data/vedic_texts/)
python scripts/ingest_corpus.py --collection vedic_texts --dir data/vedic_texts/
```

---

## Development Roadmap

| Phase | Focus | Est. Duration |
|-------|-------|--------------|
| 1 | Foundation: FastAPI + Ollama + Router + Basic UI | 2 weeks |
| 2 | Vedic Scholar + Sanskrit Grammar agents + RAG corpus | 3 weeks |
| 3 | Communication agent + Instagram webhook | 2 weeks |
| 4 | InfoSec layer + encryption + audit logging | 2 weeks |
| 5 | Survival Skills knowledge base | 1 week |
| 6 | Media engine: Whisper + OCR + indexing | 2 weeks |

---

## Key Design Decisions

**Why local-only LLM?** The ashram context requires data sovereignty. Student
communications, personal guidance requests, and community data must never
leave local infrastructure.

**Why separate agents vs one general assistant?** Each domain (sacred texts,
security, practical skills) requires different system prompts, different RAG
partitions, and different escalation rules. A single assistant would blur these.

**Why human-in-the-loop for communication?** In v1, no message should be
auto-sent to students without a teacher's review. The AI drafts; the human approves.

**Sanskrit-specific gap:** Standard LLMs have limited Sanskrit grammar accuracy.
Supplement the LLM with SanskritNLP or Sanskrit Heritage Platform API for
grammatical parsing. The LLM handles translation and commentary; the grammar
tool handles structural analysis.
