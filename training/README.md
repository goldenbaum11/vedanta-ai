# Persona training (Unsloth / NVIDIA CUDA cluster)

This directory is the **training plane**: the only part of the project
that touches ML training frameworks. It has its own venv so PyTorch/Unsloth
never enters the backend environment.

Runs on `spark-5d09` — the same box that hosts the FastAPI backend. The
admin training job spawns this as a **local** subprocess
(`backend/persona/jobs.py`), so there's no remote-execution path; training
can't be pointed at a different machine without adding that plumbing.

Moved off MLX (Apple Silicon-only) per
`docs/adr/0003-model-strategy-and-persona-training-plane.md` — the project's
actual hardware is a two-node NVIDIA GB10 (Grace Blackwell) cluster, not a
Mac. This exact CUDA 13 + Blackwell + Unsloth combination is **unverified**
— run the smoke test below before trusting it with real transcript data.

## One-time setup

```bash
cd training && ./setup.sh
```

Installs `torch` matching this box's CUDA build first, then Unsloth and
friends. If `nvidia-smi`/`nvcc --version` shows a different CUDA major
version than the script assumes, edit the `--index-url` in `setup.sh`
before running it.

**Before any real training run**, stop the deep-reasoning tier to free
VRAM on this box (it's the dominant memory user here):

```bash
systemctl --user stop llama-master.service
# ... run training ...
systemctl --user start llama-master.service
```

## Smoke test (do this before feeding it real Jonas data)

Confirm the stack actually works on this hardware with a tiny model and a
handful of synthetic pairs, before spending real time on the 27B target:

```bash
mkdir -p /tmp/smoke/{data,adapter}
cat > /tmp/smoke/data/train.jsonl <<'EOF'
{"messages": [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": "What is 2+2?"}, {"role": "assistant", "content": "4."}]}
EOF
cp /tmp/smoke/data/train.jsonl /tmp/smoke/data/valid.jsonl

./.venv/bin/python -m training.train_lora \
    --base-model unsloth/Qwen2.5-0.5B-Instruct \
    --data-dir /tmp/smoke/data \
    --adapter-dir /tmp/smoke/adapter \
    --iters 5

./.venv/bin/python -m training.generate \
    --base-model unsloth/Qwen2.5-0.5B-Instruct \
    --adapter-dir /tmp/smoke/adapter \
    --prompt "What is 2+2?"
```

If Unsloth fails on this combo, fall back to plain `transformers` + `peft`
+ `bitsandbytes` (drop `unsloth` from `requirements.txt`, adjust
`train_lora.py`/`generate.py` to use `AutoModelForCausalLM` +
`get_peft_model` directly instead of `FastLanguageModel`) — the documented
fallback in ADR-003.

## How it's used

You normally don't run anything here by hand. The admin page
(`/admin`) drives it:

1. Upload transcripts → extraction jobs produce Q&A pairs. (Turning a
   video into an uploadable transcript first needs
   `scripts/diarize_transcript.py` — see that script's docstring.)
2. Review pairs (approve/reject/edit).
3. "Start training" → exports approved pairs to
   `data/persona/dataset/mlx/{train,valid}.jsonl` and runs
   `training/train_lora.py` in this venv; logs stream into the admin UI.
4. The LoRA adapter lands in `data/persona/adapters/<model-name>/`
   (plus a `gguf/` subdirectory with a merged GGUF export) and is
   registered in the `persona_models` table.
5. "Test" on a ready model runs `training/generate.py` with the adapter.

## Manual runs (optional)

```bash
./.venv/bin/python -m training.train_lora \
    --base-model unsloth/Qwen3.8-27B \
    --data-dir data/persona/dataset/mlx \
    --adapter-dir data/persona/adapters/jonas-v1 \
    --iters 300

./.venv/bin/python -m training.generate \
    --base-model unsloth/Qwen3.8-27B \
    --adapter-dir data/persona/adapters/jonas-v1 \
    --prompt "How do I deal with a restless mind?"
```

The first training run downloads the base model from Hugging Face
(several GB, cached afterwards under `~/.cache/huggingface/`).

## Shipping a model to the chat backend

`train_lora.py` already writes a GGUF export to
`data/persona/adapters/<model-name>/gguf/` via Unsloth's built-in
`save_pretrained_gguf` — no separate conversion step needed. Point the
cluster's llama.cpp serving setup (`cluster/`) at that GGUF file the same
way it serves any other model.

The system prompt at inference MUST be `PERSONA_SYSTEM_PROMPT` from
`backend/persona/` — training and inference prompts must match or the
persona won't fire.
