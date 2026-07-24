# Persona training (MLX / Apple Silicon)

This directory is the **training plane**: the only part of the project
that touches ML training frameworks. It has its own venv so MLX never
enters the backend environment.

## One-time setup

```bash
cd training && ./setup.sh
```

## How it's used

You normally don't run anything here by hand. The admin page
(`/admin`) drives it:

1. Upload transcripts → extraction jobs produce Q&A pairs.
2. Review pairs (approve/reject/edit).
3. "Start training" → exports approved pairs to
   `data/persona/dataset/mlx/{train,valid}.jsonl` and runs
   `training/train_lora.py` in this venv; logs stream into the admin UI.
4. The LoRA adapter lands in `data/persona/adapters/<model-name>/` and
   is registered in the `persona_models` table.
5. "Test" on a ready model runs `training/generate.py` with the adapter.

## Manual runs (optional)

```bash
./.venv/bin/python -m training.train_lora \
    --base-model mlx-community/Qwen2.5-7B-Instruct-4bit \
    --data-dir data/persona/dataset/mlx \
    --adapter-dir data/persona/adapters/jonas-v1 \
    --iters 300

./.venv/bin/python -m training.generate \
    --base-model mlx-community/Qwen2.5-7B-Instruct-4bit \
    --adapter-dir data/persona/adapters/jonas-v1 \
    --prompt "How do I deal with a restless mind?"
```

The first training run downloads the base model from Hugging Face
(~4 GB, cached afterwards).

## Shipping a model to the chat backend

Fuse the adapter and convert for the serving runtime:

```bash
./.venv/bin/python -m mlx_lm fuse \
    --model mlx-community/Qwen2.5-7B-Instruct-4bit \
    --adapter-path data/persona/adapters/jonas-v1 \
    --save-path data/persona/fused/jonas-v1
```

Point LM Studio at the fused model directory (LM Studio loads MLX
models natively), then set the model name in `.env`. The system prompt
at inference MUST be `PERSONA_SYSTEM_PROMPT` from `backend/persona/`
— training and inference prompts must match or the persona won't fire.
