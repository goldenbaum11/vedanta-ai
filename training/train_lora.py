"""LoRA fine-tune wrapper around Unsloth (NVIDIA CUDA).

Invoked by the admin training job as a subprocess; everything printed to
stdout/stderr streams into the job's log in the admin UI (see
`backend/persona/jobs.py::_run_training` — that caller is unchanged; only
this script's internals moved from MLX to Unsloth, per
docs/adr/0003-model-strategy-and-persona-training-plane.md).

Expects the dataset dir to contain ``train.jsonl`` and ``valid.jsonl`` in
chat format (written by the dataset export step, base-model-agnostic):

    {"messages": [{"role": "system", ...}, {"role": "user", ...},
                  {"role": "assistant", ...}]}

Also exports a GGUF copy of the merged model next to the adapter, so the
result can be served directly by the project's existing llama.cpp/GGUF
serving stack without a separate conversion step.

Usage:
    python -m training.train_lora \\
        --base-model unsloth/Qwen3.8-27B \\
        --data-dir data/persona/dataset/mlx \\
        --adapter-dir data/persona/adapters/jonas-v1 \\
        --iters 300
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MAX_SEQ_LENGTH = 2048
LORA_TARGET_MODULES = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--adapter-dir", required=True, type=Path)
    parser.add_argument("--iters", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--num-layers",
        type=int,
        default=16,
        help="Apply LoRA to only the last N transformer layers (0 = all layers).",
    )
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    args = parser.parse_args()

    for name in ("train.jsonl", "valid.jsonl"):
        if not (args.data_dir / name).exists():
            print(f"ERROR: {args.data_dir / name} not found", flush=True)
            return 2

    args.adapter_dir.mkdir(parents=True, exist_ok=True)

    try:
        from unsloth import FastLanguageModel
    except ImportError:
        print(
            "ERROR: unsloth not installed. Run: cd training && ./setup.sh",
            flush=True,
        )
        return 2

    from datasets import load_dataset
    from transformers import TrainingArguments
    from trl import SFTTrainer

    print(f"Loading base model {args.base_model!r} (4-bit)...", flush=True)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )

    layers_to_transform = None
    if args.num_layers > 0:
        total_layers = model.config.num_hidden_layers
        n = min(args.num_layers, total_layers)
        layers_to_transform = list(range(total_layers - n, total_layers))
        print(
            f"LoRA restricted to last {n}/{total_layers} layers: "
            f"{layers_to_transform}",
            flush=True,
        )

    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=LORA_TARGET_MODULES,
        layers_to_transform=layers_to_transform,
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    print(f"Loading dataset from {args.data_dir}...", flush=True)
    dataset = load_dataset(
        "json",
        data_files={
            "train": str(args.data_dir / "train.jsonl"),
            "validation": str(args.data_dir / "valid.jsonl"),
        },
    )

    def _to_text(example: dict) -> dict:
        return {
            "text": tokenizer.apply_chat_template(
                example["messages"], tokenize=False, add_generation_prompt=False
            )
        }

    dataset = dataset.map(_to_text)

    checkpoint_dir = args.adapter_dir / "checkpoints"
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LENGTH,
        args=TrainingArguments(
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=4,
            warmup_steps=5,
            max_steps=args.iters,
            learning_rate=args.learning_rate,
            logging_steps=10,
            eval_strategy="steps",
            eval_steps=50,
            save_strategy="steps",
            save_steps=100,
            output_dir=str(checkpoint_dir),
            optim="adamw_8bit",
            report_to="none",
            disable_tqdm=True,
        ),
    )

    print("Starting training...", flush=True)
    trainer.train()

    print(f"Saving adapter to {args.adapter_dir}...", flush=True)
    model.save_pretrained(str(args.adapter_dir))
    tokenizer.save_pretrained(str(args.adapter_dir))

    gguf_dir = args.adapter_dir / "gguf"
    print(f"Exporting merged model as GGUF to {gguf_dir}...", flush=True)
    try:
        model.save_pretrained_gguf(
            str(gguf_dir), tokenizer, quantization_method="q4_k_m"
        )
    except Exception as exc:  # noqa: BLE001 - GGUF export is a bonus, not fatal
        print(
            f"WARNING: GGUF export failed ({exc}). LoRA adapter at "
            f"{args.adapter_dir} is still valid for --adapter-dir generation.",
            flush=True,
        )

    print(f"adapter written to {args.adapter_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
