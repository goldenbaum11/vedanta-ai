#!/usr/bin/env bash
# One-time setup for the persona training environment (NVIDIA CUDA / Linux).
# Creates training/.venv with Unsloth — completely separate from the
# backend's Python environment.
#
# Runs on whichever box hosts the FastAPI backend (the admin training job
# spawns this as a local subprocess — see backend/persona/jobs.py).
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
echo "Using $($PYTHON --version) at $PYTHON"

"$PYTHON" -m venv .venv
./.venv/bin/pip install --upgrade pip

# Install torch matching the box's CUDA build BEFORE the rest, so pip
# doesn't silently resolve a CPU-only or mismatched wheel as a transitive
# dep of unsloth/bitsandbytes. Check with `nvidia-smi` / `nvcc --version`
# and adjust the --index-url if this box's CUDA major version differs.
./.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu124

./.venv/bin/pip install -r requirements.txt

echo
echo "Training environment ready: training/.venv"
echo "The admin page's Start Training button will now work."
echo
echo "Before a real training run, stop the deep-reasoning tier to free"
echo "VRAM on this box:  systemctl --user stop llama-master.service"
echo "(restart it after: systemctl --user start llama-master.service)"
