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
  # max_tokens well above 10: Qwen3 (and other reasoning models) spend
  # tokens on "reasoning_content" (thinking) before any visible "content" —
  # a tight budget can be consumed entirely by thinking, leaving content
  # empty even though the model is working correctly. Accept either field
  # being non-empty so this check reflects real inference health, not a
  # thinking-budget artifact.
  RESP="$(curl -sf "${LLAMA_URL}/v1/chat/completions" \
    -H "Content-Type: application/json" "${AUTH_HEADER[@]}" \
    -d '{"messages":[{"role":"user","content":"Reply with exactly: bootstrap ok"}],"max_tokens":100}' \
    2>/dev/null)"
  if echo "$RESP" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)
msg = d['choices'][0]['message']
assert msg.get('content') or msg.get('reasoning_content')
" 2>/dev/null; then
    MODEL_NAME="$(echo "$RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('model','?'))" 2>/dev/null)"
    record PASS "model inference OK (model: $MODEL_NAME)"
  else
    record FAIL "model inference request failed or returned no content"
  fi
else
  record FAIL "model inference skipped (llama-server not reachable)"
fi

# ---------------------------------------------------------------------
section "5. Standalone 32B tier (redundant/concurrent, no RPC)"
# ---------------------------------------------------------------------
# See docs/adr/0002-serving-model-qwen3-235b-a22b.md — a second,
# independent model tier (Qwen3-32B, one instance per node, no RPC
# dependency) so the system keeps serving if the RPC-split master or
# either single node goes down.
if ! systemctl --user is-active --quiet llama-32b.service; then
  echo "  master llama-32b.service not active, attempting start..."
  systemctl --user start llama-32b.service
  sleep 3
fi
if systemctl --user is-active --quiet llama-32b.service; then
  record PASS "master llama-32b.service active"
else
  record FAIL "master llama-32b.service NOT active"
fi

while IFS=$'\t' read -r user_host rpc_port; do
  [ -z "$user_host" ] && continue
  host="${user_host#*@}"
  if ! ssh -o BatchMode=yes -o ConnectTimeout=5 "$user_host" \
      'systemctl --user is-active --quiet llama-32b.service' 2>/dev/null; then
    echo "  $user_host: llama-32b.service not active, attempting start..."
    ssh -o BatchMode=yes "$user_host" 'systemctl --user start llama-32b.service' 2>/dev/null
    sleep 3
  fi
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$user_host" \
      'systemctl --user is-active --quiet llama-32b.service' 2>/dev/null; then
    record PASS "$user_host llama-32b.service active"
  else
    record FAIL "$user_host llama-32b.service NOT active"
  fi
done <<< "$WORKERS"

API_KEY_FILE="$SCRIPT_DIR/.llama_api_key.raw"
AUTH_HEADER=()
[ -f "$API_KEY_FILE" ] && AUTH_HEADER=(-H "Authorization: Bearer $(cat "$API_KEY_FILE")")
STANDALONE_TIMEOUT_S="${STANDALONE_TIMEOUT_S:-180}"
for target in "master:127.0.0.1" "worker:10.0.0.2"; do
  label="${target%%:*}"
  host="${target##*:}"
  UP=0
  for i in $(seq 1 "$STANDALONE_TIMEOUT_S"); do
    if curl -sf "${AUTH_HEADER[@]}" "http://${host}:8081/health" >/dev/null 2>&1; then
      UP=1
      break
    fi
    sleep 1
  done
  if [ "$UP" = "1" ]; then
    record PASS "$label 32B instance /health responding ($host:8081)"
  else
    record FAIL "$label 32B instance /health not responding ($host:8081, waited ${STANDALONE_TIMEOUT_S}s)"
  fi
done

# ---------------------------------------------------------------------
section "6. LLM load balancer"
# ---------------------------------------------------------------------
if ! sg docker -c "docker inspect vedanta-llm-lb" >/dev/null 2>&1 || \
   [ "$(sg docker -c "docker inspect -f '{{.State.Running}}' vedanta-llm-lb" 2>/dev/null)" != "true" ]; then
  echo "  vedanta-llm-lb not running, attempting start..."
  sg docker -c "docker compose -f $SCRIPT_DIR/docker-compose.yml up -d" || true
  sleep 3
fi
if [ "$(sg docker -c "docker inspect -f '{{.State.Running}}' vedanta-llm-lb" 2>/dev/null)" = "true" ]; then
  record PASS "vedanta-llm-lb (Traefik) container running"
else
  record FAIL "vedanta-llm-lb (Traefik) container NOT running"
fi
# Traefik actively health-checks both backends on its own timer (see
# cluster/traefik-dynamic.yml) — :8090 itself returning any HTTP status
# means the proxy is up; 503 there means Traefik is up but has already
# detected both backends are down, which bootstrap section 5 above
# already reports on individually.
if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health 2>/dev/null | grep -qE '^[0-9]+$'; then
  record PASS "load balancer :8090 responding"
else
  record FAIL "load balancer :8090 not responding"
fi

# ---------------------------------------------------------------------
section "7. LLM tier test suite (quick/thinking/unit)"
# ---------------------------------------------------------------------
# Deeper behavioral checks than the health/routing checks above — see
# cluster/test_llm_tiers.sh for what each category covers (in particular
# "thinking", a regression guard for the Qwen3 reasoning-content budget
# issue that broke section 4's inference check — see ADR-002). Runs as
# its own script (independently useful on its own) and its per-check
# results are folded into this summary via process substitution, not a
# pipe, so they actually affect $PASS/$FAIL in this shell rather than a
# subshell that throws the count away.
if [ -x "$SCRIPT_DIR/test_llm_tiers.sh" ]; then
  TEST_OUTPUT="$("$SCRIPT_DIR/test_llm_tiers.sh" all 2>&1)"
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    status="${line%%  *}"
    msg="${line#*  }"
    record "$status" "llm-tests: $msg"
  done < <(echo "$TEST_OUTPUT" | awk '/^== Summary ==$/{flag=1; next} /^[0-9]+ passed/{flag=0} flag')
else
  record FAIL "cluster/test_llm_tiers.sh not found or not executable"
fi

# ---------------------------------------------------------------------
if [ "$WITH_APP" = "1" ]; then
section "8. App stack (docker-compose)"
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

  # NEXT_PUBLIC_API_BASE_URL is baked into the frontend's client-side JS
  # bundle at build time (see frontend/Dockerfile) — a stale bundle built
  # against the old default (http://localhost:8000) silently breaks every
  # fetch (login, chat, everything) for anyone loading the page from a
  # different machine than the server, since "localhost" then resolves to
  # *their* machine, not this one. Every check above still passes in that
  # state (they all curl from this host, where localhost is correct) —
  # this is the only check that would have caught it. See the "failed to
  # fetch" incident this guards against.
  CONFIGURED_API_URL="$(grep -m1 '^NEXT_PUBLIC_API_BASE_URL=' "$REPO_DIR/.env" 2>/dev/null | cut -d= -f2-)"
  if [ -z "$CONFIGURED_API_URL" ]; then
    record FAIL "NEXT_PUBLIC_API_BASE_URL not set in .env (frontend would default to http://localhost:8000, broken for any remote browser)"
  elif sg docker -c "docker exec vedanta-ai-frontend-1 grep -rl '$CONFIGURED_API_URL' .next/static" >/dev/null 2>&1; then
    record PASS "frontend bundle matches configured NEXT_PUBLIC_API_BASE_URL ($CONFIGURED_API_URL)"
  else
    record FAIL "frontend bundle does NOT contain configured NEXT_PUBLIC_API_BASE_URL ($CONFIGURED_API_URL) — stale build, rebuild with: docker compose build frontend && docker compose up -d frontend"
  fi
  if [ "$CONFIGURED_API_URL" != "http://localhost:8000" ] && \
     sg docker -c "docker exec vedanta-ai-frontend-1 grep -rl 'http://localhost:8000' .next/static" >/dev/null 2>&1; then
    record FAIL "frontend bundle still contains the http://localhost:8000 default alongside the configured URL — likely a partial/mixed build, rebuild frontend"
  fi
else
  section "8. App stack: skipped (--no-app)"
fi

# ---------------------------------------------------------------------
if [ "$WITH_APP" = "1" ] && [ "$WITH_DOMAIN_TESTS" = "1" ]; then
section "9. Agent domain smoke tests (end-to-end through backend)"
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
  section "9. Agent domain smoke tests: skipped"
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
