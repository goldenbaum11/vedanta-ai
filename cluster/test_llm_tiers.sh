#!/usr/bin/env bash
# Tests for the LLM serving layer itself (both tiers + load balancer) —
# complements cluster/bootstrap.sh, which checks that services are up and
# routed correctly, by exercising actual model behavior in more depth.
#
# Three categories, each independently runnable:
#
#   quick    - fast health checks across every endpoint (no inference,
#              sub-few-seconds total) — "is anything obviously down"
#   thinking - verifies Qwen3's reasoning-model behavior is correct on
#              EACH tier, in opposite directions by design: the 235B RPC
#              tier should still be thinking (reasoning_content present
#              under a tight budget, real content once given room — a
#              regression guard for the bug that broke bootstrap.sh's
#              inference check), while the standalone 32B tier should NOT
#              be thinking at all (--reasoning off — a regression guard
#              for the ~15-20s-per-request slowdown that caused, since
#              the app's intent classifier and default chat both hit this
#              tier on every request).
#   unit     - each backend tested individually and directly (bypassing
#              the load balancer for the standalone tier's two instances),
#              full chat-completion round trip, response validated against
#              the specific backend expected to have answered.
#
# Usage: cluster/test_llm_tiers.sh [quick|thinking|unit|all]
#   (default: all)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_KEY_FILE="$SCRIPT_DIR/.llama_api_key.raw"
AUTH_HEADER=()
[ -f "$API_KEY_FILE" ] && AUTH_HEADER=(-H "Authorization: Bearer $(cat "$API_KEY_FILE")")
PY="${PY:-python3}"

RPC_URL="http://172.17.0.1:8080"
STANDALONE_MASTER_URL="http://127.0.0.1:8081"
STANDALONE_WORKER_URL="http://10.0.0.2:8081"
LB_URL="http://127.0.0.1:8090"

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

chat() {
  # chat <url> <max_tokens> — returns the raw JSON response on stdout.
  # temperature=0 (greedy decoding): reasoning length otherwise varies
  # run-to-run, which made a fixed max_tokens budget flaky (observed
  # both the 235B and 32B tiers occasionally still reasoning past a
  # "generous" 150-300 token budget on non-deterministic runs) —
  # determinism matters more here than sampling diversity.
  local url="$1" max_tokens="$2"
  curl -sf "${url}/v1/chat/completions" \
    -H "Content-Type: application/json" "${AUTH_HEADER[@]}" \
    -d "{\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: test ok\"}],\"max_tokens\":${max_tokens},\"temperature\":0}" \
    2>/dev/null
}

# ---------------------------------------------------------------------
run_quick() {
section "quick: endpoint health"
# ---------------------------------------------------------------------
  for entry in "235B RPC tier:$RPC_URL" "32B master:$STANDALONE_MASTER_URL" \
               "32B worker:$STANDALONE_WORKER_URL" "load balancer:$LB_URL"; do
    label="${entry%%:*}"
    url="${entry#*:}"
    if curl -sf --max-time 3 "${url}/health" >/dev/null 2>&1; then
      record PASS "$label /health responding"
    else
      record FAIL "$label /health NOT responding"
    fi
  done
}

# ---------------------------------------------------------------------
run_thinking() {
section "thinking: Qwen3 reasoning-model behavior"
# ---------------------------------------------------------------------
  # 235B RPC tier: reasoning stays ON deliberately — this is the opt-in
  # "deep reasoning" mode (see docs/adr/0002-serving-model-qwen3-235b-a22b.md).
  for entry in "235B RPC tier:$RPC_URL"; do
    label="${entry%%:*}"
    url="${entry#*:}"

    # Tight budget: expect reasoning_content (thinking), content may be empty.
    RESP="$(chat "$url" 10)"
    if echo "$RESP" | "$PY" -c "
import sys, json
msg = json.load(sys.stdin)['choices'][0]['message']
assert msg.get('reasoning_content'), 'no reasoning_content with tight budget'
" 2>/dev/null; then
      record PASS "$label produces reasoning_content under tight max_tokens"
    else
      record FAIL "$label did not produce reasoning_content under tight max_tokens (model changed? not a reasoning model anymore?)"
    fi

    # Generous budget: expect real, non-empty content. 300, not 150 —
    # reasoning length varies run-to-run (non-deterministic generation),
    # and 150 was observed to occasionally be consumed entirely by a
    # longer-than-usual thinking trace before any answer surfaced.
    RESP="$(chat "$url" 300)"
    if echo "$RESP" | "$PY" -c "
import sys, json
msg = json.load(sys.stdin)['choices'][0]['message']
assert msg.get('content'), 'content still empty with generous budget'
" 2>/dev/null; then
      record PASS "$label produces real content under generous max_tokens"
    else
      record FAIL "$label content still empty even with generous max_tokens (regression — see bootstrap.sh section 4 fix)"
    fi
  done

  # Standalone 32B tier: reasoning is deliberately OFF (--reasoning off
  # in llama-32b-{master,worker}.service.template) — this is the
  # fast/interactive tier the app's intent classifier and default chat
  # hit on every request. Qwen3's thinking mode added ~15-20s of
  # invisible reasoning before any output even for a one-word classifier
  # label, blowing past the app's ~1-5s responsiveness target ("failed to
  # fetch"-adjacent incident: chat felt hung on a plain "hello"). These
  # checks guard the opposite direction from the 235B ones above — a
  # regression here (reasoning silently turning back on) would
  # reintroduce that exact slowdown.
  for entry in "32B master:$STANDALONE_MASTER_URL" "32B worker:$STANDALONE_WORKER_URL"; do
    label="${entry%%:*}"
    url="${entry#*:}"

    RESP="$(chat "$url" 50)"
    if echo "$RESP" | "$PY" -c "
import sys, json
msg = json.load(sys.stdin)['choices'][0]['message']
assert msg.get('content'), 'no content'
assert not msg.get('reasoning_content'), 'reasoning_content present — thinking mode is back on'
" 2>/dev/null; then
      record PASS "$label answers directly with reasoning off (no reasoning_content)"
    else
      record FAIL "$label reasoning mode regressed — check --reasoning off in llama-32b service units"
    fi
  done
}

# ---------------------------------------------------------------------
run_unit() {
section "unit: each backend individually"
# ---------------------------------------------------------------------
  # RPC tier: single instance, no ambiguity about which model path answers.
  RESP="$(chat "$RPC_URL" 150)"
  MODEL="$(echo "$RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('model','?'))" 2>/dev/null)"
  if [ -n "$MODEL" ] && [ "$MODEL" != "?" ]; then
    record PASS "235B RPC tier answers directly (model: $MODEL)"
  else
    record FAIL "235B RPC tier did not answer directly"
  fi

  # Standalone tier, master leg, hit directly (bypassing the LB).
  RESP="$(chat "$STANDALONE_MASTER_URL" 150)"
  MODEL="$(echo "$RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('model','?'))" 2>/dev/null)"
  if echo "$MODEL" | grep -q "vedantaai1"; then
    record PASS "32B standalone master answers directly (model: $MODEL)"
  else
    record FAIL "32B standalone master did not answer directly (got: $MODEL)"
  fi

  # Standalone tier, worker leg, hit directly (bypassing the LB).
  RESP="$(chat "$STANDALONE_WORKER_URL" 150)"
  MODEL="$(echo "$RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('model','?'))" 2>/dev/null)"
  if echo "$MODEL" | grep -q "vedantaai2"; then
    record PASS "32B standalone worker answers directly (model: $MODEL)"
  else
    record FAIL "32B standalone worker did not answer directly (got: $MODEL)"
  fi

  # Load balancer: fire several requests, confirm both backends actually
  # get used (round-robin), not just one absorbing everything.
  SAW_MASTER=0
  SAW_WORKER=0
  for _ in 1 2 3 4 5 6; do
    RESP="$(chat "$LB_URL" 5)"
    MODEL="$(echo "$RESP" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('model','?'))" 2>/dev/null)"
    echo "$MODEL" | grep -q "vedantaai1" && SAW_MASTER=1
    echo "$MODEL" | grep -q "vedantaai2" && SAW_WORKER=1
  done
  if [ "$SAW_MASTER" = "1" ] && [ "$SAW_WORKER" = "1" ]; then
    record PASS "load balancer distributes across both backends"
  else
    record FAIL "load balancer did not distribute across both backends (master seen: $SAW_MASTER, worker seen: $SAW_WORKER)"
  fi
}

# ---------------------------------------------------------------------
MODE="${1:-all}"
case "$MODE" in
  quick)    run_quick ;;
  thinking) run_thinking ;;
  unit)     run_unit ;;
  all)      run_quick; run_thinking; run_unit ;;
  *)        echo "Usage: $0 [quick|thinking|unit|all]"; exit 2 ;;
esac

section "Summary"
printf '%s\n' "${RESULTS[@]}"
echo
echo "$PASS passed, $FAIL failed"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
