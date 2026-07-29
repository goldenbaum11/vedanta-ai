#!/usr/bin/env bash
# Idempotent setup for a llama.cpp cluster node (head or worker).
# Builds latest llama.cpp with CUDA + RPC backend support, and creates
# a Python venv for auxiliary tooling (model download/conversion).
#
# Usage: ./setup_node.sh
# Safe to re-run: pulls latest llama.cpp and rebuilds, recreates venv deps.

set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
JOBS="${JOBS:-$(nproc)}"

echo "== Cluster node setup =="
echo "llama.cpp dir: $LLAMA_DIR"

command -v cmake >/dev/null || { echo "cmake not found"; exit 1; }
command -v git >/dev/null || { echo "git not found"; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }

CUDA_BIN="/usr/local/cuda/bin"
if [ -d "$CUDA_BIN" ]; then
  export PATH="$CUDA_BIN:$PATH"
fi
command -v nvcc >/dev/null || { echo "nvcc not found on PATH (checked $CUDA_BIN)"; exit 1; }

echo "-- nvcc: $(nvcc --version | tail -1)"
echo "-- cmake: $(cmake --version | head -1)"

if [ -d "$LLAMA_DIR/.git" ]; then
  echo "-- Updating existing llama.cpp checkout"
  git -C "$LLAMA_DIR" fetch --depth 1 origin master
  git -C "$LLAMA_DIR" reset --hard origin/master
else
  echo "-- Cloning llama.cpp (latest master)"
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"
fi

COMMIT="$(git -C "$LLAMA_DIR" rev-parse --short HEAD)"
echo "-- llama.cpp @ $COMMIT"

echo "-- Configuring build (CUDA + RPC backend, Release)"
cmake -B "$LLAMA_DIR/build" -S "$LLAMA_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA=ON \
  -DGGML_RPC=ON \
  -DLLAMA_CURL=ON

echo "-- Building (this compiles CUDA kernels, can take a while) -j$JOBS"
cmake --build "$LLAMA_DIR/build" --config Release -j"$JOBS"

echo "-- Verifying binaries"
ls -la "$LLAMA_DIR/build/bin/" | grep -E "llama-server|rpc-server|llama-cli"

echo "-- Setting up Python venv for tooling (model download/convert)"
python3 -m venv "$LLAMA_DIR/.venv"
# shellcheck disable=SC1091
source "$LLAMA_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install --upgrade -r "$LLAMA_DIR/requirements.txt"
# Pin below 1.0: transformers (via requirements.txt above) needs
# huggingface-hub<1.0, and an unconstrained [cli] install pulls the latest
# 1.x and breaks that.
pip install "huggingface_hub[cli]<1.0,>=0.34.0"
pip check
deactivate

echo "-- Recording versions to setup_state.txt"
{
  echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "llama.cpp_commit: $COMMIT"
  echo "cmake_version: $(cmake --version | head -1)"
  echo "nvcc_version: $(nvcc --version | tail -1)"
  echo "python_version: $(python3 --version)"
  echo "gpu: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo unknown)"
} > "$LLAMA_DIR/setup_state.txt"

echo "== Done. See $LLAMA_DIR/setup_state.txt for exact versions built. =="
