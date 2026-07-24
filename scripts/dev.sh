#!/usr/bin/env bash
#
# Start the whole local stack with one command:
#
#   ./scripts/dev.sh
#
# What it does:
#   1. Creates .venv/ and installs backend deps (first run only,
#      re-installs automatically when backend/requirements.txt changes)
#   2. Starts the FastAPI backend  ->  http://localhost:8000
#   3. Starts the Next.js frontend ->  http://localhost:3000
#   4. Warns (doesn't fail) if no local LLM is reachable
#
# Ctrl+C stops everything.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKEND_PORT="${APP_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

log() { printf '\033[1;33m[dev]\033[0m %s\n' "$*"; }

# Chroma's posthog telemetry client is incompatible with the posthog
# version pip resolves and spams ERROR logs at startup — disable it.
export ANONYMIZED_TELEMETRY=False

# ---------- 1. Backend venv ----------

if [ ! -x "$VENV/bin/python" ]; then
  log "Creating virtualenv at .venv/ (using $PYTHON_BIN)…"
  "$PYTHON_BIN" -m venv "$VENV"
fi

# Re-install only when requirements.txt actually changed.
REQ_STAMP="$VENV/.requirements.sha"
REQ_HASH="$(shasum backend/requirements.txt | cut -d' ' -f1)"
if [ ! -f "$REQ_STAMP" ] || [ "$(cat "$REQ_STAMP")" != "$REQ_HASH" ]; then
  log "Installing backend dependencies (first run can take a few minutes)…"
  "$VENV/bin/pip" install --upgrade pip -q
  "$VENV/bin/pip" install -q -r backend/requirements.txt
  echo "$REQ_HASH" > "$REQ_STAMP"
else
  log "Backend dependencies up to date."
fi

# ---------- 2. Frontend deps ----------

if [ ! -d frontend/node_modules ]; then
  log "Installing frontend dependencies…"
  (cd frontend && npm install)
fi

# ---------- 3. LLM reachability (warn only) ----------

if curl -sf -o /dev/null --max-time 2 http://localhost:11434/api/tags; then
  log "LLM: Ollama is up (localhost:11434)."
elif curl -sf -o /dev/null --max-time 2 http://localhost:1234/v1/models; then
  log "LLM: LM Studio is up (localhost:1234)."
else
  log "WARNING: no local LLM found on :11434 (Ollama) or :1234 (LM Studio)."
  log "         Chat and persona extraction will fail until one is running."
fi

# ---------- 4. Refuse to double-start ----------

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    log "ERROR: port $port is already in use. Stop the old process first:"
    lsof -nP -iTCP:"$port" -sTCP:LISTEN | tail -n +2
    exit 1
  fi
done

# ---------- 5. Start both, stop both on Ctrl+C ----------

PIDS=()
cleanup() {
  log "Shutting down…"
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

log "Starting backend on http://localhost:$BACKEND_PORT …"
"$VENV/bin/python" -m uvicorn backend.main:app --reload \
  --host 127.0.0.1 --port "$BACKEND_PORT" &
PIDS+=($!)

log "Starting frontend on http://localhost:$FRONTEND_PORT …"
(cd frontend && npm run dev -- --port "$FRONTEND_PORT") &
PIDS+=($!)

log "Stack is starting. Backend :$BACKEND_PORT · Frontend :$FRONTEND_PORT · Ctrl+C to stop."
wait
