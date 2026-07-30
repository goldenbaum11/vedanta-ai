# ADR-002: Serve Qwen3-235B-A22B (MoE) on the cluster instead of Llama 3.1 405B

- **Status**: Accepted
- **Date**: 2026-07-29
- **Deciders**: project owner + AI assistant
- **Phase context**: Checkpoint 6 (Containerization + Postgres), cluster serving plane

## Context

The two-node cluster (`spark-5d09` master, `spark-593d` worker, ~121 GB
RAM each, RDMA interconnect, RPC tensor-split via llama.cpp) was
originally provisioned to serve Meta-Llama-3.1-405B-Instruct
(Q4_K_M, 229 GB across 6 shards).

In production `llama-master.service` was crash-looping continuously
(60+ restarts in a single boot). Root-caused to two stacked problems:

1. **Worker RPC connection was wedged.** The worker's
   `ggml-rpc-server` had a leaked/stuck allocation from a prior aborted
   transfer (`ggml_backend_cuda_get_available_uma_memory` had dropped
   from ~122 GB free to ~2.3 GB free and never recovered) and a
   saturated accept queue (`Recv-Q=2 > backlog=1`). Every master
   startup logged `Failed to connect to 10.0.0.2:50052` within ~2s and
   silently fell back to loading the full model on the master alone
   instead of tensor-splitting it.
2. **Even after restarting the worker to clear that leak**, a
   controlled manual load test showed both nodes saturating memory
   (master 121Gi/121Gi used + swapping, worker 119Gi/121Gi used)
   *before the model finished loading*. Combined cluster RAM (~242 GB)
   barely exceeds the model's raw weight size (229 GB), leaving ~13 GB
   for KV cache, context, and activations across both nodes combined —
   not enough margin to ever load successfully, independent of the RPC
   bug.

Separately, the project's actual goal for this serving slot is not a
generic large-context assistant — it's an LLM backbone for recreating
a real Vedanta teacher's ("Jonas") persona via the LoRA pipeline in
`training/` (Q&A pair mining → adapter → served model), on top of the
existing multi-domain dispatcher (Vedic text translation, student
communication, infosec, survival skills, media). The existing serving
stack already standardized on the Qwen family — LM Studio serves
Qwen2.5-14B, and `training/` fine-tunes
`mlx-community/Qwen2.5-7B-Instruct-4bit` — specifically for
multilingual strength (English + Portuguese + Sanskrit terms).

## Decision

Serve **Qwen3-235B-A22B**, quantized as **UD-Q4_K_XL**
(`unsloth/Qwen3-235B-A22B-GGUF`, 134.1 GB across 3 shards), on the
cluster master via the existing `llama-master.service` / RPC
tensor-split path, replacing the Llama-3.1-405B plan entirely.

Llama-3.1-405B-Instruct is dropped as a candidate, not paused.

## Rationale

| Consideration | Assessment |
|---|---|
| **Fits the hardware with real headroom** | UD-Q4_K_XL is 134 GB vs. the cluster's ~242 GB combined RAM — leaves ~108 GB for KV cache/context, vs. the 13 GB margin that made 405B unloadable even with a healthy RPC link. |
| **MoE vs. dense solves the actual failure mode** | 405B is dense: all 405B params are active and must be resident + computed per token, which is why it needed the entire cluster's RAM just to load. Qwen3-235B-A22B has 235B total params but only ~22B active per token — inference cost tracks the 22B active path (roughly 32B-class latency), while the full 235B still contributes learned capacity/nuance. |
| **Family continuity with the existing stack** | The project already standardized on Qwen (Qwen2.5-14B serving, Qwen2.5-7B-Instruct-4bit for the persona LoRA adapter). Staying in-family preserves prompt formatting, tokenizer behavior, and LoRA/fine-tuning compatibility instead of restarting that validation work on a Llama base. |
| **Multilingual coverage** | Qwen3 was pretrained across ~119 languages vs. Llama 3.x's narrower coverage. Directly relevant: the dispatcher's Devanagari detection and Sanskrit terms, plus Portuguese for student communication. |
| **Capacity for persona fidelity** | 235B total parameters give more headroom to retain a specific teacher's nuanced philosophical/teaching style faithfully (the `training/` pipeline's stated goal: "extraction only, never rewriting, so the teacher's literal words are preserved") than a 70B-class dense model would. |
| **No change needed on the worker node** | RPC tensor-split means only the master needs the `.gguf` files locally; the worker (`spark-593d`) runs `ggml-rpc-server` as a bare compute backend with no model file of its own. No duplicate ~134 GB download required. |

### Alternatives considered

| Option | Why not chosen |
|---|---|
| **Llama-3.1-405B-Instruct (Q4_K_M, 229 GB)** | Dense; all params active per token; doesn't fit cluster RAM with usable headroom regardless of RPC health. Original crash-loop root cause. |
| **Llama-3.1-70B-Instruct (Q8_0)** | Fits a single node easily and was the first fallback, but breaks continuity with the Qwen-based persona/LoRA pipeline and has narrower multilingual coverage than Qwen3. Partial download (~3 GB of 75 GB) abandoned before completion. |
| **Qwen3-32B (dense)** | Safest, simplest single-node upgrade from the current Qwen2.5-14B — still viable as a smaller/faster fallback if 235B-A22B proves too slow in practice. |
| **Qwen3-235B-A22B at Q4_K_M / Q5_K_M / Q6_K** | Same model, heavier quant (142 GB / 167 GB / 193 GB) — less headroom for context for marginal quality gain over UD-Q4_K_XL, whose unsloth "dynamic" quantization keeps higher precision on the layers most sensitive to error (notably MoE routing weights). |
| **Mixtral 8x22B / DeepSeek-V2.5 (other MoE families)** | Viable MoE alternatives in the same size class, but break Qwen family continuity with the existing persona/LoRA pipeline for no compensating benefit. |

## Consequences

### Positive

- Cluster can actually load and run without OOM-killing itself, given the fixed RPC worker connection and adequate headroom.
- Persona (Jonas) fine-tuning stays in the Qwen lineage already validated in `training/`.
- Better multilingual grounding for Sanskrit/Portuguese without extra tooling.
- MoE efficiency means inference latency should track a ~32B-class model despite the larger total knowledge capacity.

### Negative

- MoE serving in llama.cpp has more moving parts (expert routing) than a dense model; worth a controlled load test (in progress) before wiring into the always-on systemd unit.
- 134 GB download vs. an already-local 229 GB (405B) / 4.6 GB (8B) — one-time bandwidth/time cost.
- If the persona LoRA adapters are eventually retrained against this base instead of Qwen2.5-7B, that's additional training-plane work (separate from this ADR).

### Neutral

- `llama-master.service`'s `Restart=on-failure` / `RestartSec=3` crash-loop risk remains structurally present if the RPC worker wedges again; this ADR doesn't change that policy, only the model being loaded. Worth a follow-up ADR or fix if the worker-side leak recurs.

## Revisit triggers

- MoE routing/expert-swap latency in llama.cpp proves too slow in practice → fall back to Qwen3-32B dense.
- The worker RPC connection wedges again under real load → investigate `ggml-rpc-server` connection-handling/leak fix rather than just restarting it each time.
- Persona LoRA fine-tuning on this base underperforms the Qwen2.5-7B baseline → reconsider base model for the training plane specifically (serving and training bases don't have to match, but currently do by convention).

## References

- `cluster/nodes.yaml`, `cluster/llama-master.service.template`, `cluster/llama-rpc-worker.service` — cluster topology and unit definitions.
- `docs/TECH_STACK.md` — existing Qwen2.5-14B serving / Qwen2.5-7B-Instruct-4bit training-base rationale.
- `training/README.md` — persona pipeline (Q&A extraction, LoRA adapters).
- `docs/adr/0001-no-langchain.md` — ADR format/convention followed here.
- `unsloth/Qwen3-235B-A22B-GGUF`, `Qwen/Qwen3-235B-A22B-GGUF` — GGUF sources evaluated.
