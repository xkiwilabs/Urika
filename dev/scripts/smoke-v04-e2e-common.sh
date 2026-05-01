#!/usr/bin/env bash
# Common helpers for the v0.4 end-to-end smoke scripts.
#
# Each E2E script sources this file. The helpers establish:
#   - PASS/FAIL counters
#   - log() / step() / ok() / fail() / verify_artifact()
#   - run_step_with_timeout() — runs a long-lived `urika ...` invocation
#     with a generous timeout, captures output to a per-step log,
#     asserts on output content
#
# Unlike the unit-style smoke (smoke-v04-cli.sh) these scripts hit
# the real Anthropic API end-to-end. Each one creates a project in
# the user's REAL ~/urika-projects/ directory so it shows up in the
# dashboard for visual inspection. By default the script does NOT
# clean up the project at the end — pass --cleanup as the last arg
# to wipe the project on success.

set -uo pipefail

if [[ -z "${URIKA_E2E_LOG_DIR:-}" ]]; then
  URIKA_E2E_LOG_DIR="$(pwd)/dev/scripts/.smoke-logs/$(date +%Y%m%d-%H%M%S)-$$"
  export URIKA_E2E_LOG_DIR
fi
mkdir -p "$URIKA_E2E_LOG_DIR"

# Strip Claude-Code session markers so the bundled / system claude
# CLI doesn't refuse to nest. Mirrors the SDK adapter scrub at the
# bash invocation layer.
unset CLAUDECODE CLAUDE_CODE_SSE_PORT CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_EXECPATH 2>/dev/null || true

PASS=0
FAIL=0
RESULTS=()

log() { echo "  $*" | tee -a "$URIKA_E2E_LOG_DIR/run.log"; }
step() {
  echo
  echo "=== $* ===" | tee -a "$URIKA_E2E_LOG_DIR/run.log"
}
ok() {
  RESULTS+=("PASS  $1")
  PASS=$((PASS+1))
  echo "  ✓ PASS: $1" | tee -a "$URIKA_E2E_LOG_DIR/run.log"
}
fail() {
  RESULTS+=("FAIL  $1")
  FAIL=$((FAIL+1))
  echo "  ✗ FAIL: $1" | tee -a "$URIKA_E2E_LOG_DIR/run.log"
  if [[ -n "${2:-}" ]]; then echo "    detail: $2" | tee -a "$URIKA_E2E_LOG_DIR/run.log"; fi
}

# Run a urika command with timeout, logging stdout/stderr to a per-step
# file. Returns 0 on zero exit AND non-empty output AND no SDK error
# markers. Args: <step-name> <timeout-seconds> <urika-args...>
run_step_with_timeout() {
  local name="$1"; shift
  local seconds="$1"; shift
  local logfile="$URIKA_E2E_LOG_DIR/${name// /_}.log"
  log "▸ ${seconds}s timeout — output: $logfile"
  if timeout "$seconds" "$@" > "$logfile" 2>&1; then
    # Fail only on *actionable* SDK regressions, not on noise the
    # adapter already tolerates. Specifically:
    #   - ``can_use_tool callback requires`` — streaming-mode bug
    #     we already patched (regression marker).
    #   - A Python traceback referencing our adapter module — means
    #     the adapter raised, not that the SDK logged something.
    # The bare "Fatal error in message reader" string used to be a
    # FAIL trigger but the SDK emits it as benign noise after the
    # system claude CLI exits 1 post-stream — the adapter's
    # ``trailing_exit_after_success`` branch already returned a
    # successful AgentResult by that point, and the urika command
    # itself exits 0. Greping for it produced false positives.
    if grep -qE "can_use_tool callback requires" "$logfile"; then
      fail "$name" "$(grep -m1 -E 'can_use_tool callback requires' "$logfile")"
      return 1
    fi
    if grep -qE "Traceback \(most recent" "$logfile" \
       && grep -qE "urika/agents/adapters/claude_sdk\.py" "$logfile"; then
      fail "$name" "$(grep -m1 -E 'Traceback|urika/agents/adapters' "$logfile")"
      return 1
    fi
    ok "$name"
    return 0
  else
    fail "$name" "non-zero exit (or timeout); see $logfile"
    return 1
  fi
}

verify_artifact() {
  local desc="$1"
  local path="$2"
  if [[ -e "$path" ]]; then ok "artifact exists: $desc"
  else fail "artifact missing: $desc ($path)"
  fi
}

verify_artifact_contains() {
  local desc="$1"
  local path="$2"
  local needle="$3"
  if [[ -e "$path" ]] && grep -qE "$needle" "$path"; then
    ok "artifact contains \"$needle\": $desc"
  else
    fail "artifact missing/empty: $desc ($path)" "needle=\"$needle\""
  fi
}

print_summary() {
  echo
  echo "============================================================"
  echo "E2E smoke summary:"
  for r in "${RESULTS[@]}"; do echo "  $r"; done
  echo "------------------------------------------------------------"
  echo "  PASS: $PASS"
  echo "  FAIL: $FAIL"
  echo "  Logs: $URIKA_E2E_LOG_DIR/"
  echo "============================================================"
}
