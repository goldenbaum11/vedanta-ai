# Local-first LLM engineer — llama.cpp, self-hosted (part-time contract)

Remote · 15–25 h/week to start · [rate or range] · contract, ongoing if
it works out

## The project

We teach Vedanta to students in Brazil and abroad, and we're building an
AI study assistant on our own hardware. It answers questions about the
scriptures in Portuguese, English, and Sanskrit, cites the exact passage
for every quote, and — the long-term goal — answers the way our teacher
actually teaches, trained on fifteen years of his recorded classes.

Most of it exists and runs: a chat interface, a retrieval system over
~2,200 scripture passages, an admin console with a working LoRA
fine-tuning pipeline, and a two-node Linux cluster running a 235B MoE
model through llama.cpp's RPC tensor-split. This is not a napkin sketch;
you'd be joining a working system with a test suite and docs.

Everything runs on machines we own. That's a principle, not a budget
constraint.

## The work, in order

**First month — stabilize serving.** Our deep-reasoning tier points at a
cluster node that's currently offline; scripture questions fall back to
a placeholder. We also learned the hard way (documented in an ADR) what
happens when a model doesn't fit in RAM. We want: a right-sized model
serving reliably, health checks and alerting so silent failures can't
happen again, and clean systemd units. You should be able to look at a
GGUF quant and our RAM and know if it fits before downloading 40 GB.

**After that — the class archive.** Years of recorded classes, to be
transcribed, cleaned, and made searchable, so the assistant can say "the
teacher explained this in a 2011 class" and link the moment. Sanskrit
terms break normal ASR, so this is careful pipeline work, not a script.

**Ongoing — the teacher's voice.** The LoRA pipeline (extract Q&A pairs
from transcripts → human review → fine-tune → deploy) is built and has
produced working adapters. It needs data at scale and iteration on
quality.

## You

- Have run LLMs on your own hardware with **llama.cpp** — quantization,
  memory budgeting, and what to do when it OOMs
- Are at home on **plain Linux servers**: systemd, logs, memory pressure
- Write working **Python** (our backend is FastAPI in Docker)
- Bonus: ASR on difficult audio, Portuguese, LoRA/QLoRA experience

## How we work

Small team, direct conversation, a lot of freedom, decisions written
down as ADRs. Two rules that don't bend: nothing runs on other
companies' servers, and no models with safety training stripped out —
students sometimes bring real personal difficulty to this assistant.

If you think we've made a wrong call, say so before the work, not after.

## Apply

Email [address] with a short note: a time you ran models on your own
machines, something that broke, and what you changed so it stopped
breaking. A link to anything you've built or written beats a CV.
