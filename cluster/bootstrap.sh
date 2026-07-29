#!/usr/bin/env bash
# Full cold-start check for the Vedanta AI stack: interconnect network,
# RPC workers, cluster master (llama-server), a real model inference
# check, the docker-compose app stack, and an end-to-end smoke test per
# agent domain. Runs on every boot via vedanta-bootstrap.service (see
# cluster/README.md) — also safe to run manually any time.
#
# Unlike a plain `set -e` script, this runs EVERY check regardless of
# earlier failures and prints a full pass/fail summary at the end, so one
# broken thing doesn't hide problems elsewhere. Exit code is 0 only if
# everything passed.
#
# Usage: cluster/bootstrap.sh [--no-app] [--no-domain-tests]
#   --no-app:           skip the docker-compose app stack (cluster only)
#   --no-domain-tests:  skip the per-agent-domain LLM smoke tests (faster)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
PY="$LLAMA_DIR/.venv/bin/python3"

WITH_APP=1
WITH_DOMAIN_TESTS=1
for arg in "$@"; do
  [ "$arg" = "--no-app" ] && WITH_APP=0
  [ "$arg" = "--no-domain-tests" ] && WITH_DOMAIN_TESTS=0
done

PASS=0
FAIL=0
declare -a RESULTS=()

record() {
  # record <PASS|FAIL> <message>
  if [ "$1" = "PASS" ]; then
    PASS=$((PASS + 1))
    RESULTS+=("PASS  $2")
  else
    FAIL=$((FAIL + 1))
    RESULTS+=("FAIL  $2")
  fi
  echo "$1: $2"
}

section() { echo; echo "== $1 =="; }

# ---------------------------------------------------------------------
section "1. Interconnect network"
# ---------------------------------------------------------------------
WORKERS="$("$PY" "$SCRIPT_DIR/parse_workers.py" "$SCRIPT_DIR/nodes.yaml")"
while IFS=$'\t' read -r user_host rpc_port; do
  [ -z "$user_host" ] && continue
  host="${user_host#*@}"
  if ping -c 2 -W 2 "$host" >/dev/null 2>&1; then
    record PASS "interconnect ping to $host"
  else
    record FAIL "interconnect ping to $host (worker unreachable — check cable/link)"
  fi
done <<< "$WORKERS"

# ---------------------------------------------------------------------
section "2. RPC workers"
# ---------------------------------------------------------------------
while IFS=$'\t' read -r user_host rpc_port; do
  [ -z "$user_host" ] && continue
  host="${user_host#*@}"
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$user_host" \
      'systemctl --user is-active --quiet llama-rpc-worker.service' 2>/dev/null; then
    echo "  $user_host: service not active, attempting start..."
    ssh -o BatchMode=yes "$user_host" 'systemctl --user start llama-rpc-worker.service' 2>/dev/null
    sleep 2
  fi
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$user_host" \
      'systemctl --user is-active --quiet llama-rpc-worker.service' 2>/dev/null; then
    record PASS "$user_host llama-rpc-worker.service active"
  else
    record FAIL "$user_host llama-rpc-worker.service NOT active"
  fi
  if timeout 3 bash -c "echo > /dev/tcp/${host}/${rpc_port}" 2>/dev/null; then
    record PASS "$user_host RPC port $rpc_port reachable"
  else
    record FAIL "$user_host RPC port $rpc_port NOT reachable"
  fi
done <<< "$WORKERS"

# ---------------------------------------------------------------------
section "3. Master (llama-server)"
# ---------------------------------------------------------------------
if ! systemctl --user is-active --quiet llama-master.service; then
  echo "  not active, attempting start..."
  systemctl --user start llama-master.service
  sleep 3
fi
if systemctl --user is-active --quiet llama-master.service; then
  record PASS "llama-master.service active"
else
  record FAIL "llama-master.service NOT active"
fi

# Large models can take minutes to mmap/load into VRAM — retry generously
# rather than declaring failure while it's still loading.
MODEL_LOAD_TIMEOUT_S="${MODEL_LOAD_TIMEOUT_S:-600}"
LLAMA_URL=""
for i in $(seq 1 "$MODEL_LOAD_TIMEOUT_S"); do
  for candidate in http://127.0.0.1:8080 http://172.17.0.1:8080; do
    if curl -sf "${candidate}/health" >/dev/null 2>&1; then
      LLAMA_URL="$candidate"
      break 2
    fi
  done
  sleep 1
done
if [ -n "$LLAMA_URL" ]; then
  record PASS "llama-server /health responding at $LLAMA_URL"
else
  record FAIL "llama-server /health not responding on 127.0.0.1 or 172.17.0.1:8080 (waited ${MODEL_LOAD_TIMEOUT_S}s)"
fi

# ---------------------------------------------------------------------
section "4. Model inference"
# ---------------------------------------------------------------------
if [ -n "$LLAMA_URL" ]; then
  API_KEY_FILE="$SCRIPT_DIR/.llama_api_key.raw"
  AUTH_HEADER=()
  [ -f "$API_KEY_FILE" ] && AUTH_HEADER=(-H "Authorization: Bearer $(cat "$API_KEY_FILE")")
  RESP="$(curl -sf "${LLAMA_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" "${AUTH_HEADER[@]}" \
    -d '{"messages":[{"role":"user","content":"Reply with exactly: bootstrap ok"}],"max_tokens":10}' \
    2>/dev/null)"
  if echo "$RESP" | "$PY" -c "import sys,json; d=json.load(sys.stdin); assert d['choices'][0]['message']['content']" 2>/dev/null; then
    MODEL_NAME="$(echo "$RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('model','?'))" 2>/dev/null)"
    record PASS "model inference OK (model: $MODEL_NAME)"
  else
    record FAIL "model inference request failed or returned no content"
  fi
else
  record FAIL "model inference skipped (llama-server not reachable)"
fi

# ---------------------------------------------------------------------
if [ "$WITH_APP" = "1" ]; then
section "5. App stack (docker-compose)"
  cd "$REPO_DIR"
  if sg docker -c "docker compose up -d" >/tmp/vedanta-bootstrap-compose.log 2>&1; then
    record PASS "docker compose up"
  else
    record FAIL "docker compose up (see /tmp/vedanta-bootstrap-compose.log)"
  fi
  BACKEND_UP=0
  for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
      BACKEND_UP=1
      break
    fi
    sleep 1
  done
  if [ "$BACKEND_UP" = "1" ]; then
    record PASS "backend /health responding"
  else
    record FAIL "backend /health not responding after 30s"
  fi
  if curl -sf -o /dev/null http://localhost:3000; then
    record PASS "frontend reachable on :3000"
  else
    record FAIL "frontend not reachable on :3000"
  fi
else
  section "5. App stack: skipped (--no-app)"
fi

# ---------------------------------------------------------------------
if [ "$WITH_APP" = "1" ] && [ "$WITH_DOMAIN_TESTS" = "1" ]; then
section "6. Agent domain smoke tests (end-to-end through backend)"
  declare -A DOMAIN_MSGS=(
    [vedic_scholar]="Translate Bhagavad Gita verse 2.47 into English."
    [sanskrit_grammar]="Explain the sandhi rule in this Sanskrit compound word."
    [communication]="I would like to schedule an ashram visit and RSVP for the event."
    [infosec]="Please audit our recent login access logs for any anomaly."
    [survival]="What is a good ayurveda herbal remedy for a cold?"
    [media]="Can you transcribe this audio recording and generate a caption?"
  )
  for expected_agent in "${!DOMAIN_MSGS[@]}"; do
    msg="${DOMAIN_MSGS[$expected_agent]}"
    payload="$("$PY" -c "import json,sys; print(json.dumps({'message': sys.argv[1]}))" "$msg")"
    resp="$(curl -sf -X POST http://localhost:8000/api/v1/chat \
      -H "Content-Type: application/json" -d "$payload" 2>/dev/null)"
    got_agent="$(echo "$resp" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('agent','?'))" 2>/dev/null)"
    if [ "$got_agent" = "$expected_agent" ]; then
      record PASS "domain '$expected_agent' routed correctly"
    else
      record FAIL "domain '$expected_agent' routed to '$got_agent' instead"
    fi
  done
else
  section "6. Agent domain smoke tests: skipped"
fi

# ---------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------
printf '%s\n' "${RESULTS[@]}"
echo
echo "$PASS passed, $FAIL failed"
STATUS_FILE="$SCRIPT_DIR/.last_bootstrap_status"
{
  echo "timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "passed: $PASS"
  echo "failed: $FAIL"
} > "$STATUS_FILE"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
