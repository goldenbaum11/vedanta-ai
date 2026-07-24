"""LoRA fine-tune wrapper around mlx-lm (Apple Silicon).

Invoked by the admin training job as a subprocess; everything printed
to stdout streams into the job's log in the admin UI. Expects the
dataset dir to contain ``train.jsonl`` and ``valid.jsonl`` in MLX chat
format (written by the dataset export step):

    {"messages": [{"role": "system", ...}, {"role": "user", ...},
                  {"role": "assistant", ...}]}

Usage:
    python -m training.train_lora \\
        --base-model mlx-community/Qwen2.5-7B-Instruct-4bit \\
        --data-dir data/persona/dataset/mlx \\
        --adapter-dir data/persona/adapters/jonas-v1 \\
        --iters 300
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--adapter-dir", required=True, type=Path)
    parser.add_argument("--iters", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-layers", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    args = parser.parse_args()

    for name in ("train.jsonl", "valid.jsonl"):
        if not (args.data_dir / name).exists():
            print(f"ERROR: {args.data_dir / name} not found", flush=True)
            return 2

    args.adapter_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "mlx_lm", "lora",
        "--model", args.base_model,
        "--train",
        "--data", str(args.data_dir),
        "--adapter-path", str(args.adapter_dir),
        "--iters", str(args.iters),
        "--batch-size", str(args.batch_size),
        "--num-layers", str(args.num_layers),
        "--learning-rate", str(args.learning_rate),
        "--steps-per-report", "10",
        "--steps-per-eval", "50",
        "--save-every", "100",
    ]
    print("trainer command:", " ".join(cmd), flush=True)
    # Stream output unbuffered so the admin job log updates live.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
    code = proc.wait()
    if code != 0:
        print(f"ERROR: mlx_lm lora exited with {code}", flush=True)
        return code

    print(f"adapter written to {args.adapter_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
