#!/usr/bin/env bash
# Run on the master node. Starts llama-server (OpenAI-compatible API) and
# offloads layers to every worker listed in nodes.yaml over RPC.
#
# Usage: ./start_master.sh /path/to/model.gguf [extra llama-server args...]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
# Default to localhost: the vedanta-ai backend runs on this same machine
# (see OPENAI_COMPATIBLE_BASE_URL in .env). Only widen BIND_HOST if the
# backend runs elsewhere, and set API_KEY if you do — llama-server has no
# auth by default and would otherwise be an open, unauthenticated endpoint.
BIND_HOST="${BIND_HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
# Path to a file containing just the raw key (no KEY=VALUE prefix) — kept
# out of `ps`/`systemctl status`/command-line entirely via --api-key-file,
# unlike passing the key as a CLI arg.
API_KEY_FILE="${API_KEY_FILE:-}"

if [ "$BIND_HOST" != "127.0.0.1" ] && [ -z "$API_KEY_FILE" ]; then
  echo "Refusing to bind $BIND_HOST without API_KEY_FILE set (llama-server has no auth by default)." >&2
  echo "Set API_KEY_FILE=<path to raw-key file> or use BIND_HOST=127.0.0.1." >&2
  exit 1
fi

MODEL_PATH="${1:-}"
[ -n "$MODEL_PATH" ] || { echo "Usage: $0 <model.gguf> [extra llama-server args...]"; exit 1; }
shift || true

BIN="$LLAMA_DIR/build/bin/llama-server"
[ -x "$BIN" ] || { echo "llama-server binary not found at $BIN — run setup_node.sh first"; exit 1; }

RPC_ARGS=()
NGL_ARGS=()
if [ "${SKIP_RPC:-0}" = "1" ]; then
  echo "SKIP_RPC=1: running local-GPU-only, no tensor-split (fine for models that fit on one node)"
  # Single device, nothing to balance — force full GPU offload outright.
  NGL_ARGS=(-ngl 999)
else
  RPC_LIST="$("$LLAMA_DIR/.venv/bin/python3" "$SCRIPT_DIR/parse_nodes.py" "$SCRIPT_DIR/nodes.yaml")"
  [ -n "$RPC_LIST" ] || { echo "No workers found in nodes.yaml (set SKIP_RPC=1 to run local-only)"; exit 1; }
  echo "Workers (RPC): $RPC_LIST"
  RPC_ARGS=(--rpc "$RPC_LIST")
  # Deliberately NOT forcing -ngl here: --fit (on by default) is what
  # computes both n_gpu_layers AND the per-device tensor-split across
  # local + RPC devices based on each device's free memory. Forcing
  # -ngl 999 disables that calculation entirely ("n_gpu_layers already
  # set by user to 999, abort" in the log) and — observed in practice —
  # causes it to load the whole model onto the local device only, while
  # the RPC worker sits idle, ballooning local memory toward OOM instead
  # of actually splitting. Let --fit run; override with NGL_OVERRIDE=N
  # or TENSOR_SPLIT=N0,N1,... below only if you need to hand-tune it.
  [ -n "${NGL_OVERRIDE:-}" ] && NGL_ARGS=(-ngl "$NGL_OVERRIDE")
fi

echo "Starting master llama-server on ${BIND_HOST}:${PORT}, model: $MODEL_PATH"

TENSOR_SPLIT_ARGS=()
[ -n "${TENSOR_SPLIT:-}" ] && TENSOR_SPLIT_ARGS=(--tensor-split "$TENSOR_SPLIT")

# --mlock pins every touched page in RAM, unable to be evicted. For a
# single-node model that's harmless and helps (no swap/compression once
# loaded). For an RPC/multi-node model bigger than local RAM, it's
# actively harmful: llama.cpp reads through the whole (possibly
# multi-part) file to catalog tensors and compute the --fit device split
# BEFORE any data is actually offloaded to a worker, and with mlock
# active none of those pages can be reclaimed in the meantime — so local
# memory hits a hard OOM ceiling before offload ever begins, even though
# the eventual on-device footprint (this node's share only) would easily
# fit. Confirmed via observation: an 8B model (fits in RAM even mlock'd)
# split correctly across master+worker; loading a 229GB model (6-part
# GGUF) with --mlock exceeded 111GB locally, worker untouched, over and
# over. Default mlock off for the RPC path; on for local-only (SKIP_RPC=1)
# where the file always fits and eviction risk doesn't apply. Override
# with MLOCK=1/0 explicitly if needed.
if [ "${SKIP_RPC:-0}" = "1" ]; then
  MLOCK_DEFAULT=1
else
  MLOCK_DEFAULT=0
fi
MLOCK_ARGS=()
[ "${MLOCK:-$MLOCK_DEFAULT}" = "1" ] && MLOCK_ARGS=(--mlock)

# --direct-io: bypasses the mmap-based tensor upload path entirely,
# reading straight from disk into pre-allocated buffers instead. This is
# the documented fix for a known llama.cpp bug where RPC-split loads of
# large models hang indefinitely partway through (see upstream issues
# ggml-org/llama.cpp #24813, #19745, #11552) — the mmap→GPU/RPC upload
# path deadlocks for models this size. Confirmed independently here too:
# our load hung in D-state (uninterruptible disk sleep) right after a
# CUDA_Host pinned-buffer allocation fallback. Default on for the RPC
# path; irrelevant for local-only (SKIP_RPC=1) where it hasn't been an
# issue, but harmless there too.
DIRECT_IO_ARGS=()
if [ "${SKIP_RPC:-0}" != "1" ] && [ "${DIRECT_IO:-1}" = "1" ]; then
  DIRECT_IO_ARGS=(--direct-io)
fi

API_KEY_ARGS=()
[ -n "$API_KEY_FILE" ] && API_KEY_ARGS=(--api-key-file "$API_KEY_FILE")

exec "$BIN" \
  --model "$MODEL_PATH" \
  "${RPC_ARGS[@]}" \
  --host "$BIND_HOST" \
  --port "$PORT" \
  "${NGL_ARGS[@]}" \
  "${TENSOR_SPLIT_ARGS[@]}" \
  "${MLOCK_ARGS[@]}" \
  "${DIRECT_IO_ARGS[@]}" \
  "${API_KEY_ARGS[@]}" \
  "$@"
