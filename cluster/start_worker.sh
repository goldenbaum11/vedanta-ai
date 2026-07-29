#!/usr/bin/env bash
# Run on a worker node. Exposes this machine's GPU to the master over the
# interconnect via llama.cpp's RPC backend. No model files needed here —
# the master streams weights to us at load time.

set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
# Safe-by-default: ggml-rpc-server has NO authentication, so binding
# 0.0.0.0 would expose raw GPU/RPC access on every interface (Wi-Fi, LAN).
# Set BIND_HOST explicitly to this node's private interconnect IP (see
# nodes.yaml) — the systemd unit does this via an Environment= override.
BIND_HOST="${BIND_HOST:-127.0.0.1}"
PORT="${PORT:-50052}"

BIN="$LLAMA_DIR/build/bin/ggml-rpc-server"
[ -x "$BIN" ] || { echo "rpc-server binary not found at $BIN — run setup_node.sh first"; exit 1; }

echo "Starting RPC worker on ${BIND_HOST}:${PORT} (cache enabled)"
exec "$BIN" --host "$BIND_HOST" --port "$PORT" --cache
