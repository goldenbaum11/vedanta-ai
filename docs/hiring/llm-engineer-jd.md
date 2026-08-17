# AI/LLM Engineer — Virtual Vedanta Teacher (Part-Time Contract)

Remote · 15–25 h/week to start · [rate or range] · contract, ongoing if
it works out

## The goal

Create a virtual version of our Vedanta teacher, Jonas:

- Answers the way Jonas actually teaches — his voice, style, and method
- Grounded in a real knowledge base: the scriptures (Portuguese,
  English, Sanskrit) and ~15 years of his recorded classes
- Every quote backed by a citation to the exact passage or class
- Runs entirely on our own hardware — nothing on other companies'
  servers

A lot already exists: chat interface, retrieval over ~2,200 scripture
passages, a working LoRA fine-tuning pipeline with an admin console, and
a two-node llama.cpp cluster. You would own the path from "works" to
"sounds like Jonas."

## Key responsibilities

**1. Evaluate the current implementation**
- Review what we've built: RAG setup, LoRA pipeline, serving cluster
- Tell us what to keep, what to refine, and what to replace — and why

**2. Define the right model approach**
- How many models do we need (chat, persona, embeddings, reasoning)?
- Which base models, at which sizes, optimized for our hardware?
- Written recommendation with trade-offs (we document decisions as ADRs)

**3. Own the training / fine-tuning approach**
- Refine how we turn texts and decades of recorded classes into
  training data (transcription, cleaning, Q&A extraction, review)
- Improve fine-tuning quality and set up honest evaluation — does it
  actually sound like Jonas, and is it faithful to the teaching?

**4. Establish a repeatable process**
- Document the full loop (data → review → train → evaluate → deploy) so
  someone who isn't you can run it and continue the work
- This is a lasting system, not a one-off experiment

**5. Keep it running**
- Reliable self-hosted serving: right-sized models, health checks,
  alerts when something breaks instead of silent failures

## Requirements

- Hands-on LLM fine-tuning experience (LoRA/QLoRA) — not only API calls
- Have run models on your own hardware (llama.cpp or similar): memory
  budgeting, quantization, knowing what fits before downloading 40 GB
- Comfortable on plain Linux servers: systemd, logs, debugging OOMs
- Solid Python (our backend is FastAPI in Docker)
- Can evaluate a system you didn't build and argue for changes clearly

**Nice to have**
- Speech-to-text on difficult audio (Sanskrit terms break normal ASR)
- Portuguese
- RAG systems where citation accuracy actually matters

## How we work

- Small team, direct conversation, a lot of freedom
- Decisions written down as ADRs
- Two rules that don't bend: nothing runs on other companies' servers,
  and no models with safety training stripped out — students sometimes
  bring real personal difficulty to this assistant
- If you think we've made a wrong call, say so before the work, not
  after

## Apply

Email [address] with a short note:

- A time you fine-tuned or ran models on your own machines
- Something that broke, and what you changed so it stopped breaking
- A link to anything you've built or written beats a CV
