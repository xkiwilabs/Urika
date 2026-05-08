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

# v0.4.3 Track 2d: cheap-config smoke variant.
#
# By default the smoke uses a smaller / cheaper model split
# (sonnet for reasoning, haiku for execution) and a reduced
# max-turns so dev iteration on the harness itself is fast and
# inexpensive (~$0.50, ~10 min). This catches plumbing bugs
# (orchestrator loop, parsing, atomic writes, prompt assembly,
# advisor handoff) without burning opus per iteration.
#
# Pre-release validation flips back to the canonical opus + 5-turn
# config: ``URIKA_SMOKE_REAL=1 bash dev/scripts/smoke-v04-e2e-open.sh``.
# The release-to-main.sh canonical flow doesn't auto-set this — the
# user invokes the smoke explicitly before tagging.
if [[ "${URIKA_SMOKE_REAL:-0}" == "1" ]]; then
    URIKA_SMOKE_MAX_TURNS_OPEN=5
    URIKA_SMOKE_MAX_TURNS_HYBRID=5
    URIKA_SMOKE_MODE_LABEL="REAL (opus + 5 turns)"
    URIKA_SMOKE_INJECT_CHEAP_MODELS=0
else
    URIKA_SMOKE_MAX_TURNS_OPEN=3
    URIKA_SMOKE_MAX_TURNS_HYBRID=2
    URIKA_SMOKE_MODE_LABEL="CHEAP (sonnet + haiku, reduced turns)"
    URIKA_SMOKE_INJECT_CHEAP_MODELS=1
fi
export URIKA_SMOKE_MAX_TURNS_OPEN URIKA_SMOKE_MAX_TURNS_HYBRID URIKA_SMOKE_MODE_LABEL URIKA_SMOKE_INJECT_CHEAP_MODELS

# Helper: write per-agent model overrides into a freshly-created
# project's urika.toml so the cheap-config smoke uses sonnet for
# reasoning and haiku for execution. Project-level overrides win
# over the global ``[runtime.modes.<mode>].models`` settings, so
# this is fully scoped to the smoke project — the user's global
# config is unchanged.
#
# No-op when URIKA_SMOKE_INJECT_CHEAP_MODELS=0 (real mode).
inject_cheap_models() {
    local proj_dir="$1"
    if [[ "${URIKA_SMOKE_INJECT_CHEAP_MODELS:-0}" != "1" ]]; then
        return 0
    fi
    if [[ ! -f "$proj_dir/urika.toml" ]]; then
        log "⚠ inject_cheap_models: $proj_dir/urika.toml not found, skipping"
        return 0
    fi
    log "▸ Injecting cheap-config models (sonnet + haiku) into project urika.toml"
    cat >> "$proj_dir/urika.toml" <<'EOF'

# v0.4.3 Track 2d cheap-smoke override: pin reasoning agents to
# sonnet and execution agents to haiku for this project only.
# Set URIKA_SMOKE_REAL=1 in the environment to skip this block.
[runtime.models.planning_agent]
model = "claude-sonnet-4-5"

[runtime.models.advisor_agent]
model = "claude-sonnet-4-5"

[runtime.models.evaluator]
model = "claude-sonnet-4-5"

[runtime.models.finalizer]
model = "claude-sonnet-4-5"

[runtime.models.report_agent]
model = "claude-sonnet-4-5"

[runtime.models.presentation_agent]
model = "claude-sonnet-4-5"

[runtime.models.task_agent]
model = "claude-haiku-4-5"

[runtime.models.tool_builder]
model = "claude-haiku-4-5"
EOF
}

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

# Pass when ANY of the supplied paths exists. v0.4.0 renamed the
# project-level deck dir from ``presentation/`` to
# ``final-presentation/``; the smoke harness was still asserting
# only the old name and reporting a false-positive failure on every
# hybrid / private run after the rename. Use this for any artifact
# whose location can vary between equivalent layouts.
verify_artifact_any() {
  local desc="$1"; shift
  for p in "$@"; do
    if [[ -e "$p" ]]; then
      ok "artifact exists: $desc ($p)"
      return 0
    fi
  done
  fail "artifact missing: $desc (none of: $*)"
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
