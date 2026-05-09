# ADR-001: Do not adopt LangChain; defer LangGraph to Phase 3

- **Status**: Accepted
- **Date**: 2026-05-08
- **Deciders**: project owner + AI assistant
- **Phase context**: end of Phase 2 (Vedic Text Intelligence)

## Context

Two adjacent ecosystems were evaluated as candidates for orchestrating
the multi-agent Vedanta AI system:

1. **LangChain** — broad framework providing LLM clients, document
   loaders, text splitters, vector store wrappers, retrievers, prompt
   templates, and chains.
2. **LangGraph** — sister library providing stateful graph-based
   workflow orchestration (cycles, multi-agent collaboration, tool
   calling, checkpointing, human-in-the-loop).

The decision matters now because the project rules emphasise
local-first operation, minimal dependencies, and direct control over
the LLM/RAG stack — and because by end of Phase 2 we have already
built provider-agnostic LLM and embedding clients, verse-aware
chunkers, a hybrid (metadata-pinned + semantic) retriever, and an
agent dispatcher in roughly 600 lines of focused code.

## Decision

### LangChain — **rejected**

We will not adopt LangChain as a project framework. Specifically:

- **Reject** `langchain.chains`, `langchain.agents`, `langchain.memory`,
  `langchain.retrievers`. We have already built fitter equivalents.
- **Acceptable, case-by-case**: importing a single
  `langchain_community.document_loaders.X` for an exotic format we
  genuinely need (e.g. MediaWiki XML, Notion export). Pin tightly and
  isolate behind our own chunker interface.
- **Acceptable transitively**: `langchain-core` will arrive when we
  adopt LangGraph in Phase 3. Its surface (Runnable interface, message
  types) is small, stable, and not problematic.

### LangGraph — **deferred to Phase 3**

We will not adopt LangGraph in Phase 1 or Phase 2. We *will* introduce
it in Phase 3 (Communication Agent), where multi-turn conversation
memory, supervised multi-agent flows, and tool calling create
legitimate orchestration needs. Until then, the dispatcher pattern
(`backend/router/dispatcher.py`) is sufficient.

The agent interface — `async def handle(query, context) -> AgentResponse`
— deliberately matches what a LangGraph node looks like, so existing
agents become nodes when we migrate.

## Rationale

### Why reject LangChain

| Consideration | Assessment |
|---|---|
| **Surface duplication** | LangChain's core utilities (LLM clients, embedding clients, vector store wrappers, retrievers, document loaders) are already implemented in `backend/models/`, `backend/rag/`, and `backend/knowledge/`. Adopting LangChain means rewriting working code. |
| **Specificity** | Our hybrid retrieval (metadata-pinning verse references *before* semantic search) is tuned for this project's exact failure mode. LangChain's stock retrievers don't ship this. |
| **Local-first** | Cursor rules require all user data stays on local infrastructure. LangChain's LangSmith telemetry is opt-out, not opt-in. |
| **Dependency cost** | Full LangChain pulls ~30 transitive dependencies and ~200 MB. |
| **API stability** | LangChain has had multiple breaking renames in 18 months (`langchain` → `langchain-core` + `-community` + `-experimental`); LCEL syntax has shifted. |
| **Async** | Our pipeline is `async`/`await` end-to-end. LangChain's async support has historically been retrofitted with parity gaps. |
| **Cognitive overhead** | Every contributor would have to learn LangChain's mental model on top of the project's. |

### Why defer (not reject) LangGraph

| Consideration | Assessment |
|---|---|
| **Premature today** | We use zero of LangGraph's superpowers (cycles, multi-agent collaboration, tool calling, checkpointing, human-in-the-loop, parallel fan-out, intermediate-state streaming). |
| **Right tool eventually** | Phase 3 introduces multi-turn conversation memory and likely tool calling for the Communication agent. Phase 4+ may need cross-domain (multi-agent) flows. These are LangGraph's sweet spot. |
| **Migration friction** | Low. Existing agents are already shaped like LangGraph nodes. |
| **Dependency cost** | `langchain-core` only — much smaller than full LangChain, and stable. |

### Lighter alternatives we considered

| Tool | When it would be enough |
|---|---|
| **`pydantic-ai`** | If we want typed structured outputs without graph orchestration. |
| **`instructor`** | If the only pain is "I want JSON, not free text". |
| **Plain `asyncio.gather` + state machine** | For 1–2 specific orchestration needs. |

We will reach for the lightest of these first when concrete pain
emerges, and only adopt LangGraph when at least one of these triggers
fires:

- A query needs ≥2 cooperating agents (cross-domain).
- A workflow needs a retry-on-low-confidence cycle.
- An agent needs deterministic tool calling.
- The UI needs streaming intermediate state ("retrieving… thinking…").
- A flow requires checkpointed multi-turn memory.

## Consequences

### Positive

- ~600 lines of project-specific code remain readable and easy to evolve.
- No dependency on LangChain's release cadence or breaking changes.
- Local-first guarantee remains uncomplicated (no LangSmith, no
  surprise telemetry).
- Hybrid retrieval, prompt structure, citation format remain entirely
  under our control.

### Negative

- We must continue maintaining our own LLM clients, retriever, and
  chunkers. (Mitigation: they're small, well-tested in practice, and
  match our use case.)
- When we onboard contributors familiar with LangChain, they'll need
  a brief orientation to our equivalents.
- We do not get LangChain's ~200 community document loaders for free.
  (Mitigation: rare in practice; case-by-case import when needed.)

### Neutral

- Future migration to LangGraph in Phase 3 remains low-friction.

## Revisit triggers

This ADR should be re-opened if:

- Any of the LangGraph "trigger" conditions above fire and we need an
  orchestration layer beyond the dispatcher.
- LangChain ships a stable, slim, telemetry-free `langchain-core`-only
  package with the integrations we'd want.
- We decide to support a non-local LLM provider (e.g. OpenAI hosted),
  which would change the local-first calculus.

## References

- `vedanta_ai_cursor_prompt.md` — multi-phase project spec.
- `.cursorrules` — code style and architectural guardrails.
- `backend/models/llm_client.py` — provider-agnostic LLM client.
- `backend/models/embedding_client.py` — provider-agnostic embedding
  client.
- `backend/rag/retriever.py` — hybrid retrieval implementation.
- `backend/router/dispatcher.py` — current orchestration layer.
