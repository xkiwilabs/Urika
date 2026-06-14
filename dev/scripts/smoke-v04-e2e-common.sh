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
# v0.10.0 Phase 9: a third outcome for steps that failed for a purely
# transient API reason (stream timeout, 429/RESOURCE_EXHAUSTED,
# overloaded/503/529) AND were retried once and still flaked. TRANSIENT
# does NOT contribute to the exit code — a pure API-weather run exits 0.
TRANSIENT=0
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

# v0.7.0 Task 4.5: provider → default model helpers.
#
# Used by the multi-provider smoke modes (``--provider`` and
# ``--mixed-providers`` on ``smoke-v04-e2e-open.sh``). Keep the
# defaults aligned with ``urika.agents.registry.recommended_models_for``
# so the smoke exercises the same models a user would pick up by
# default after ``urika config <provider>``.
#
# Reasoning models drive planning_agent / advisor_agent / evaluator /
# finalizer / report_agent / presentation_agent; execution models
# drive task_agent / tool_builder.
provider_default_reasoning_model() {
  case "$1" in
    anthropic) echo "claude-opus-4-7" ;;
    openai) echo "gpt-5.4" ;;
    # Google: Flash for BOTH roles (free-tier-friendly default; see
    # ``urika.core.recommended_models``). ``gemini-3.1-pro-preview``
    # requires a billing-enabled Google AI account.
    google) echo "gemini-3.5-flash" ;;
    *) echo "ERROR: unknown provider $1" >&2; exit 1 ;;
  esac
}

provider_default_execution_model() {
  case "$1" in
    anthropic) echo "claude-sonnet-4-5" ;;
    openai) echo "gpt-5.4-mini" ;;
    google) echo "gemini-3.5-flash" ;;
    *) echo "ERROR: unknown provider $1" >&2; exit 1 ;;
  esac
}

# v0.7.0 Task 4.5: write per-agent provider/model overrides into a
# freshly-created project's urika.toml.
#
# Single-provider mode (provider passed as arg):
#   reasoning agents → provider_default_reasoning_model(<provider>)
#   execution agents → provider_default_execution_model(<provider>)
#
# Mixed mode (special sentinel "__mixed__"):
#   planning_agent → Anthropic reasoning
#   task_agent     → OpenAI execution
#   advisor_agent  → Google reasoning
#   remaining roles → Anthropic defaults (so the run completes even
#                     if only the three target adapters are pinned).
#
# Overrides this project's urika.toml only — global config is
# untouched. Mutually exclusive with ``inject_cheap_models`` (caller
# decides which to invoke based on PROVIDER / MIXED_PROVIDERS).
_bump_top_level_runtime_model() {
  # Replace the top-level [runtime] model = "..." line with a new value.
  # Required for honest --provider smokes: the orchestrator loop
  # (run/autonomous/finalize) uses runner_for_project(project_path)
  # which reads top-level [runtime] model, NOT per-agent overrides.
  # Without this bump, --provider X would test X only on the support-
  # agent CLI paths (advisor/build-tool/present/etc.) and silently
  # leave the orchestrator loop on the default claude model.
  local proj_toml="$1"
  local new_model="$2"
  awk -v new_model="$new_model" '
    /^\[runtime\]$/ { in_rt=1; print; next }
    in_rt && /^model[[:space:]]*=/ { print "model = \"" new_model "\""; in_rt=0; next }
    /^\[/ { in_rt=0 }
    { print }
  ' "$proj_toml" > "$proj_toml.tmp" && mv "$proj_toml.tmp" "$proj_toml"
}

inject_provider_models() {
  local proj_dir="$1"
  local provider="$2"
  if [[ ! -f "$proj_dir/urika.toml" ]]; then
    log "warning: inject_provider_models: $proj_dir/urika.toml not found, skipping"
    return 0
  fi
  if [[ "$provider" == "__mixed__" ]]; then
    log "Injecting MIXED-PROVIDER models (planner=Anthropic, task=OpenAI, advisor=Google)"
    local anth_r anth_e oai_e goog_r
    anth_r="$(provider_default_reasoning_model anthropic)"
    anth_e="$(provider_default_execution_model anthropic)"
    oai_e="$(provider_default_execution_model openai)"
    goog_r="$(provider_default_reasoning_model google)"
    # Orchestrator loop uses top-level model; in mixed mode pin it
    # to Anthropic's reasoning model (planner is Anthropic in the mix).
    _bump_top_level_runtime_model "$proj_dir/urika.toml" "$anth_r"
    cat >> "$proj_dir/urika.toml" <<EOF

# v0.7.0 Task 4.5 mixed-providers smoke override: distribute roles
# across all three adapters so a single run exercises every code path.
[runtime.models.planning_agent]
model = "${anth_r}"

[runtime.models.task_agent]
model = "${oai_e}"

[runtime.models.advisor_agent]
model = "${goog_r}"

[runtime.models.evaluator]
model = "${anth_r}"

[runtime.models.finalizer]
model = "${anth_r}"

[runtime.models.report_agent]
model = "${anth_r}"

[runtime.models.presentation_agent]
model = "${anth_r}"

[runtime.models.tool_builder]
model = "${anth_e}"
EOF
    return 0
  fi

  local rmodel emodel
  rmodel="$(provider_default_reasoning_model "$provider")"
  emodel="$(provider_default_execution_model "$provider")"
  log "Injecting ${provider} models (reasoning=${rmodel}, execution=${emodel})"
  # Orchestrator loop uses top-level model; pin it to this provider's
  # reasoning model so run/autonomous/finalize route via the right adapter.
  _bump_top_level_runtime_model "$proj_dir/urika.toml" "$rmodel"
  cat >> "$proj_dir/urika.toml" <<EOF

# v0.7.0 Task 4.5 single-provider smoke override (--provider ${provider}):
# pin every agent to the ${provider} adapter for this project.
[runtime.models.planning_agent]
model = "${rmodel}"

[runtime.models.advisor_agent]
model = "${rmodel}"

[runtime.models.evaluator]
model = "${rmodel}"

[runtime.models.finalizer]
model = "${rmodel}"

[runtime.models.report_agent]
model = "${rmodel}"

[runtime.models.presentation_agent]
model = "${rmodel}"

[runtime.models.task_agent]
model = "${emodel}"

[runtime.models.tool_builder]
model = "${emodel}"
EOF
}

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
# v0.10.0 Phase 9: a step that failed transiently even after one retry.
# Recorded + reported, but NON-fatal (does not bump FAIL, does not
# affect the exit code). Mirrors fail()'s shape.
transient() {
  RESULTS+=("TRANSIENT  $1")
  TRANSIENT=$((TRANSIENT+1))
  echo "  ~ TRANSIENT: $1" | tee -a "$URIKA_E2E_LOG_DIR/run.log"
  if [[ -n "${2:-}" ]]; then echo "    detail: $2" | tee -a "$URIKA_E2E_LOG_DIR/run.log"; fi
}

# Classify a step's log as a transient API failure (return 0/true) vs a
# real failure (return non-zero/false). A step is transient iff:
#   (a) the log contains at least one transient marker, AND
#   (b) the log contains NO real-error marker.
#
# Transient markers (API weather — retryable, not our bug):
#   Agent stream timeout / RuntimeError: Agent stream timeout,
#   RESOURCE_EXHAUSTED, 429, rate limit, overloaded_error,
#   Error code: 529, 503 Service Unavailable. (case-insensitive)
#
# Real-error markers (a code bug — DISQUALIFY transient even if a
# transient marker is also present): AssertionError, KeyError,
# TypeError, SyntaxError, ModuleNotFoundError. A bare Traceback is NOT
# a real-error marker on its own: a pure stream-timeout aborts the
# asyncio task and prints a CancelledError traceback that is not a code
# bug. A urika-source-referencing Traceback only counts as real when
# there is NO stream-timeout marker present (i.e. the traceback wasn't
# caused by the timeout teardown).
_is_transient_failure() {
  local logfile="$1"
  [[ -f "$logfile" ]] || return 1

  # (a) must have a transient marker
  local transient_re='Agent stream timeout|RESOURCE_EXHAUSTED|429|rate limit|overloaded_error|Error code: 529|503 Service Unavailable'
  grep -qiE "$transient_re" "$logfile" || return 1

  # (b1) explicit code-error exception types always disqualify.
  if grep -qE 'AssertionError|KeyError|TypeError|SyntaxError|ModuleNotFoundError' "$logfile"; then
    return 1
  fi

  # (b2) a urika-source-referencing traceback disqualifies ONLY when no
  # stream-timeout marker is present (a stream timeout legitimately
  # unwinds through urika code via CancelledError without being a bug).
  if grep -qE 'Traceback \(most recent' "$logfile" \
     && grep -qE 'urika/' "$logfile" \
     && ! grep -qiE 'Agent stream timeout' "$logfile"; then
    return 1
  fi

  return 0
}

# Run a urika command with timeout, logging stdout/stderr to a per-step
# file. Returns 0 on zero exit AND non-empty output AND no SDK error
# markers. Args: <step-name> <timeout-seconds> <urika-args...>
# Run a single attempt of a urika command into <logfile>. Echoes a
# verdict line on stdout-of-the-function (captured by the caller):
#   PASS                  — zero exit, no actionable SDK regression marker
#   FAIL\t<detail>        — real failure (non-zero exit/timeout, or an
#                           actionable SDK regression marker)
# The caller (run_step_with_timeout) decides retry / transient policy.
# Args: <timeout-seconds> <logfile> <urika-args...>
_run_step_attempt() {
  local seconds="$1"; shift
  local logfile="$1"; shift
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
      printf 'FAIL\t%s' "$(grep -m1 -E 'can_use_tool callback requires' "$logfile")"
      return 0
    fi
    if grep -qE "Traceback \(most recent" "$logfile" \
       && grep -qE "urika/agents/adapters/claude_sdk\.py" "$logfile"; then
      printf 'FAIL\t%s' "$(grep -m1 -E 'Traceback|urika/agents/adapters' "$logfile")"
      return 0
    fi
    printf 'PASS'
    return 0
  else
    printf 'FAIL\t%s' "non-zero exit (or timeout); see $logfile"
    return 0
  fi
}

run_step_with_timeout() {
  local name="$1"; shift
  local seconds="$1"; shift
  local logfile="$URIKA_E2E_LOG_DIR/${name// /_}.log"
  log "▸ ${seconds}s timeout — output: $logfile"

  local verdict detail
  verdict="$(_run_step_attempt "$seconds" "$logfile" "$@")"
  detail="${verdict#*$'\t'}"; [[ "$detail" == "$verdict" ]] && detail=""
  verdict="${verdict%%$'\t'*}"

  if [[ "$verdict" == "PASS" ]]; then
    ok "$name"
    return 0
  fi

  # Real (non-transient) failure → fail immediately, no retry.
  if ! _is_transient_failure "$logfile"; then
    fail "$name" "$detail"
    return 1
  fi

  # Transient failure → retry the same command ONCE with a fresh log.
  log "▸ transient API failure on \"$name\" — retrying once"
  local retry_log="$URIKA_E2E_LOG_DIR/${name// /_}.retry.log"
  local rverdict rdetail
  rverdict="$(_run_step_attempt "$seconds" "$retry_log" "$@")"
  rdetail="${rverdict#*$'\t'}"; [[ "$rdetail" == "$rverdict" ]] && rdetail=""
  rverdict="${rverdict%%$'\t'*}"

  if [[ "$rverdict" == "PASS" ]]; then
    ok "$name (passed on retry after a transient failure)"
    return 0
  fi
  # Retry also failed: transient again → non-fatal; real → fail.
  if _is_transient_failure "$retry_log"; then
    transient "$name" "transient API failure persisted across one retry; see $retry_log"
    return 0
  fi
  fail "$name" "$rdetail"
  return 1
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

# Agent-written PROSE needs more than existence/size: a read-only report
# agent can leave its NARRATION ("I'll write a report... I successfully
# wrote...") in the file instead of the report. These assert the artifact
# is actually a report. (Added after a ~3900-byte narration blob landed in
# projectbook/final-report.md and passed every existence/size check.)
_NARRATION_MARKERS='I.?ll write|I.?ll now|Let me |I have successfully|I.?ve successfully|successfully written|successfully wrote|Let me check if the file|Here.?s (the|a)|Let me read|Let me start by|I am going to|I.?m going to'

# <desc> <path> [min_sections=2]
verify_markdown_report() {
  local desc="$1"; local path="$2"; local min_sections="${3:-2}"
  if [[ ! -s "$path" ]]; then fail "$desc — missing/empty: $path"; return 1; fi
  local first; first="$(grep -m1 -E '\S' "$path" || true)"
  if [[ ! "$first" =~ ^#+[[:space:]] ]]; then
    fail "$desc — first non-blank line is not a markdown heading" "got: ${first:0:80}"; return 1
  fi
  local hit; hit="$(grep -m1 -iE "$_NARRATION_MARKERS" "$path" || true)"
  if [[ -n "$hit" ]]; then
    fail "$desc — contains agent narration, not a report" "marker: ${hit:0:90}"; return 1
  fi
  local n; n="$(grep -cE '^#+[[:space:]]' "$path" || true)"
  if (( n < min_sections )); then fail "$desc — only $n heading(s) (expected >=$min_sections)"; return 1; fi
  ok "$desc ($n sections, no narration)"
}

# Weaker: non-empty + leading heading + no chatter (for short docs)
# <desc> <path>
verify_markdown_not_chatter() {
  local desc="$1"; local path="$2"
  if [[ ! -s "$path" ]]; then fail "$desc — missing/empty: $path"; return 1; fi
  local first; first="$(grep -m1 -E '\S' "$path" || true)"
  if [[ ! "$first" =~ ^#+[[:space:]] ]]; then
    fail "$desc — first non-blank line is not a markdown heading" "got: ${first:0:80}"; return 1
  fi
  local hit; hit="$(grep -m1 -iE "$_NARRATION_MARKERS" "$path" || true)"
  if [[ -n "$hit" ]]; then fail "$desc — contains agent narration" "marker: ${hit:0:90}"; return 1; fi
  ok "$desc"
}

# Presentation must be a RENDERED deck, not an empty shell.
# <desc> <path>
verify_presentation_rendered() {
  local desc="$1"; local path="$2"
  if [[ ! -s "$path" ]]; then fail "$desc — missing/empty: $path"; return 1; fi
  local slides imgs
  slides="$(grep -coE '<section[ >]' "$path" || true)"
  imgs="$(grep -coE '<img[ >]' "$path" || true)"
  if (( slides < 1 )); then fail "$desc — no <section> slides ($path)"; return 1; fi
  if (( imgs < 1 )); then fail "$desc — $slides slides but 0 <img> figures" "$path"; return 1; fi
  ok "$desc ($slides slides, $imgs figures)"
}

# --- "did real work" assertions ------------------------------------
#
# The existence checks above only prove a command didn't crash and
# laid down a skeleton — they pass even when `urika run` exits early
# having recorded zero runs (the loop creates experiments/ and an
# empty leaderboard.json before any agent runs). These helpers look
# at the *content* the agents are supposed to have produced.

# Resolve the most-recently-created experiment dir for a project,
# or empty string if there are none. Sorted lexically — experiment
# IDs are timestamp-prefixed so the last one is the newest.
_latest_experiment_dir() {
  local proj_dir="$1"
  local exp_root="$proj_dir/experiments"
  [[ -d "$exp_root" ]] || return 0
  local d=""
  for d in "$exp_root"/*/; do :; done
  [[ -d "$d" ]] && echo "${d%/}"
}

# Run a python one-liner that exits 0/1; pass the step on exit 0.
# Args: <desc> <python-source>. The source gets PROJ_DIR / EXP_DIR
# from the environment (callers export them).
_verify_py() {
  local desc="$1"; local src="$2"
  if python3 -c "$src" 2>>"$URIKA_E2E_LOG_DIR/run.log"; then
    ok "$desc"
  else
    fail "$desc"
  fi
}

# After `urika run` for a single experiment: the latest experiment
# must have recorded >=1 run in progress.json AND leaderboard.json
# must be a non-empty JSON array. A run that exits early — for any
# of the reasons in the v0.4.* audit (uncategorised first-turn
# error, sandbox-denied Bash, advisor parse miss, empty agent
# output) — fails here instead of sailing through on exit 0.
verify_run_did_work() {
  local desc="$1"; local proj_dir="$2"
  local exp_dir; exp_dir="$(_latest_experiment_dir "$proj_dir")"
  if [[ -z "$exp_dir" ]]; then
    fail "$desc — no experiment directory under $proj_dir/experiments"
    return 1
  fi
  PROJ_DIR="$proj_dir" EXP_DIR="$exp_dir" _verify_py "$desc" '
import json, os, sys
exp = os.environ["EXP_DIR"]
proj = os.environ["PROJ_DIR"]
prog = json.load(open(os.path.join(exp, "progress.json")))
runs = prog.get("runs", [])
if len(runs) < 1:
    print(f"  progress.json has {len(runs)} runs (expected >=1) in {exp}", file=sys.stderr)
    sys.exit(1)
lb_path = os.path.join(proj, "leaderboard.json")
lb = json.load(open(lb_path)) if os.path.exists(lb_path) else []
# leaderboard may be a list of entries or a dict keyed by something.
entries = lb if isinstance(lb, list) else (lb.get("entries") or lb.get("runs") or list(lb.values()) if isinstance(lb, dict) else [])
if not entries:
    print(f"  leaderboard.json is empty: {lb_path}", file=sys.stderr)
    sys.exit(1)
'
}

# session.json for the latest experiment must show >=1 completed
# turn (the loop only persists current_turn after a turn finishes,
# so >=1 means the loop body ran at least once — not "started then
# died before doing anything").
verify_turns_ran() {
  local desc="$1"; local proj_dir="$2"; local min_turns="${3:-1}"
  local exp_dir; exp_dir="$(_latest_experiment_dir "$proj_dir")"
  if [[ -z "$exp_dir" ]]; then
    fail "$desc — no experiment directory"
    return 1
  fi
  PROJ_DIR="$proj_dir" EXP_DIR="$exp_dir" MIN_TURNS="$min_turns" _verify_py "$desc" '
import json, os, sys
exp = os.environ["EXP_DIR"]
n = int(os.environ["MIN_TURNS"])
s = json.load(open(os.path.join(exp, "session.json")))
ct = s.get("current_turn", 0)
if ct < n:
    sys.stderr.write("  session.json current_turn=%s (expected >=%s) status=%r in %s\n" % (ct, n, s.get("status"), exp))
    sys.exit(1)
'
}

# After `urika run --max-experiments N`: there must be >=N experiment
# directories. Catches the meta-loop bailing with 0 (or 1) experiments
# when the advisor's suggestions block doesn't parse.
verify_min_experiments() {
  local desc="$1"; local proj_dir="$2"; local n="$3"; local log="${4:-}"
  # The advisor legitimately stops the meta loop early when existing
  # experiments already satisfy the project criteria ("no further
  # experiments to suggest"). Counting dirs alone flagged that CORRECT
  # behavior as a failure (seen 2026-06-10: exp-001 met all
  # confirmatory criteria with 3 converging methods, advisor declined
  # a 2nd experiment). When the caller passes the autonomous log and
  # it shows the advisor declined, accept the lower count — the
  # companion verify_each_experiment_did_work assertion still requires
  # the experiments that DID run to have recorded real runs. v0.8.0.
  if [[ -n "$log" && -f "$log" ]] \
       && grep -qi "no further experiments to suggest" "$log"; then
    ok "$desc (advisor declined: criteria already satisfied)"
    return 0
  fi
  PROJ_DIR="$proj_dir" N="$n" _verify_py "$desc" '
import os, sys
root = os.path.join(os.environ["PROJ_DIR"], "experiments")
n = int(os.environ["N"])
dirs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))] if os.path.isdir(root) else []
if len(dirs) < n:
    print(f"  found {len(dirs)} experiment dirs (expected >={n}): {sorted(dirs)}", file=sys.stderr)
    sys.exit(1)
'
}

# findings.json (written by the *finalizer agent* via its Write tool —
# nothing in Python produces it, so this is the only guard) must parse,
# carry a non-empty plain-text ``answer``, and list >=1 final method
# with a ``script`` path. A run that recorded real work but whose
# finalizer produced an empty skeleton fails here.
verify_findings_nonempty() {
  local desc="$1"; local path="$2"
  PATH_IN="$path" _verify_py "$desc" '
import json, os, sys
p = os.environ["PATH_IN"]
d = json.load(open(p))
if not isinstance(d, dict) or not d:
    print(f"  findings.json is empty/not a dict: {p}", file=sys.stderr); sys.exit(1)
ans = d.get("answer") or d.get("summary")
if not (isinstance(ans, str) and ans.strip()):
    print(f"  findings.json has no non-empty answer/summary: {p}", file=sys.stderr); sys.exit(1)
methods = d.get("final_methods") or d.get("methods") or d.get("selected_methods") or d.get("best_methods")
if not (isinstance(methods, list) and methods):
    print(f"  findings.json lists no final methods: {p}", file=sys.stderr); sys.exit(1)
'
}

# >=1 recorded run in the latest experiment must carry a NON-EMPTY
# metrics dict. (A RunRecord may legitimately have ``metrics: {}`` when
# the task agent reports a data-loading error in the record, so we
# don't require *all* runs to have metrics — but if none do, the
# experiment produced no real result.)
verify_run_metrics_nonempty() {
  local desc="$1"; local proj_dir="$2"
  local exp_dir; exp_dir="$(_latest_experiment_dir "$proj_dir")"
  if [[ -z "$exp_dir" ]]; then fail "$desc — no experiment directory"; return 1; fi
  EXP_DIR="$exp_dir" _verify_py "$desc" '
import json, os, sys
exp = os.environ["EXP_DIR"]
prog = json.load(open(os.path.join(exp, "progress.json")))
runs = prog.get("runs", [])
ok = [r for r in runs if isinstance(r.get("metrics"), dict) and r["metrics"]]
if not ok:
    print(f"  no run in {exp} has a non-empty metrics dict (runs={len(runs)})", file=sys.stderr)
    sys.exit(1)
'
}

# methods.json must exist with >=1 well-formed entry, and the
# project-level bookkeeping must be mutually consistent: every
# leaderboard entry'\''s method is in methods.json, and every method in
# methods.json appears as a run in some experiment. Catches the
# sub-agent-overwrote-methods.json class and registry/leaderboard drift.
verify_methods_consistent() {
  local desc="$1"; local proj_dir="$2"
  PROJ_DIR="$proj_dir" _verify_py "$desc" '
import json, os, sys
proj = os.environ["PROJ_DIR"]
mpath = os.path.join(proj, "methods.json")
if not os.path.exists(mpath):
    print(f"  methods.json missing: {mpath}", file=sys.stderr); sys.exit(1)
md = json.load(open(mpath))
methods = md.get("methods", []) if isinstance(md, dict) else []
names = [m.get("name") for m in methods if isinstance(m, dict)]
if not names or not all(isinstance(n, str) and n for n in names):
    print(f"  methods.json has no well-formed entries: {names!r}", file=sys.stderr); sys.exit(1)
nameset = set(names)
# leaderboard.json -> ranking entries reference known methods
lbpath = os.path.join(proj, "leaderboard.json")
if os.path.exists(lbpath):
    lb = json.load(open(lbpath))
    rank = lb.get("ranking") if isinstance(lb, dict) else (lb if isinstance(lb, list) else [])
    for e in rank or []:
        m = e.get("method") if isinstance(e, dict) else None
        if m is not None and m not in nameset:
            print(f"  leaderboard references method {m!r} not in methods.json {nameset}", file=sys.stderr); sys.exit(1)
# every method appears as a run somewhere
run_methods = set()
expdir = os.path.join(proj, "experiments")
for d in (os.listdir(expdir) if os.path.isdir(expdir) else []):
    pj = os.path.join(expdir, d, "progress.json")
    if os.path.exists(pj):
        try:
            for r in json.load(open(pj)).get("runs", []):
                if isinstance(r, dict) and r.get("method"):
                    run_methods.add(r["method"])
        except Exception:
            pass
orphan = nameset - run_methods
if orphan:
    print(f"  methods.json entries with no matching run: {orphan}", file=sys.stderr); sys.exit(1)
'
}

# The finalizer'\''s reproducibility artifacts must be REAL, not empty
# stubs (they are all agent-written via the Write tool):
#   - requirements.txt: >=1 non-comment, non-blank line that looks like
#     a pip requirement.
#   - reproduce.sh: non-empty, has a shebang on line 1, references
#     requirements.txt, and runs at least one ``methods/final_*.py``.
#   - >=1 standalone ``methods/final_*.py`` exists and is syntactically
#     valid Python.
# With URIKA_SMOKE_REAL=1: additionally create a throwaway venv and
# ``pip install -r requirements.txt`` into it (proves the deps the
# finalizer listed are actually installable).
verify_finalize_artifacts_real() {
  local desc="$1"; local proj_dir="$2"
  PROJ_DIR="$proj_dir" _verify_py "${desc} — files have real content" '
import os, re, sys, glob, ast
proj = os.environ["PROJ_DIR"]
# requirements.txt
req = os.path.join(proj, "requirements.txt")
lines = [ln.strip() for ln in open(req).read().splitlines()] if os.path.exists(req) else []
pkgs = [ln for ln in lines if ln and not ln.startswith("#")]
if not pkgs or not any(re.match(r"^[A-Za-z0-9_.\-]+", p) for p in pkgs):
    print(f"  requirements.txt has no real package lines: {req}", file=sys.stderr); sys.exit(1)
# reproduce.sh
rep = os.path.join(proj, "reproduce.sh")
txt = open(rep).read() if os.path.exists(rep) else ""
if not txt.strip():
    print(f"  reproduce.sh missing/empty: {rep}", file=sys.stderr); sys.exit(1)
if not txt.splitlines()[0].startswith("#!"):
    print(f"  reproduce.sh has no shebang: {rep}", file=sys.stderr); sys.exit(1)
if "requirements.txt" not in txt:
    print(f"  reproduce.sh does not reference requirements.txt", file=sys.stderr); sys.exit(1)
if "methods/final_" not in txt:
    print(f"  reproduce.sh does not run any methods/final_*.py", file=sys.stderr); sys.exit(1)
# standalone method scripts
finals = glob.glob(os.path.join(proj, "methods", "final_*.py"))
if not finals:
    print(f"  no methods/final_*.py written by the finalizer", file=sys.stderr); sys.exit(1)
for f in finals:
    try:
        ast.parse(open(f).read())
    except SyntaxError as e:
        print(f"  standalone method {f} is not valid Python: {e}", file=sys.stderr); sys.exit(1)
'
  # Optional, expensive: prove the requirements actually install.
  if [[ "${URIKA_SMOKE_REAL:-0}" == "1" ]]; then
    local venv="$URIKA_E2E_LOG_DIR/repro-venv"
    if python3 -m venv "$venv" >>"$URIKA_E2E_LOG_DIR/run.log" 2>&1 \
       && "$venv/bin/pip" install -q -r "$proj_dir/requirements.txt" >>"$URIKA_E2E_LOG_DIR/run.log" 2>&1; then
      ok "${desc} — requirements.txt installs in a clean venv"
    else
      fail "${desc} — pip install -r requirements.txt failed in a clean venv"
    fi
  fi
}

# --- v0.9.0 output-polish artifact checks ---------------------------
#
# `urika finalize` now also writes, via best-effort hooks in
# orchestrator/finalize.py (a hook failure logs a progress event but
# never blocks finalize — so the smoke is the only end-to-end guard
# that they actually fired):
#   - projectbook/reproduce.ipynb   (core/notebook_export.py)
#   - projectbook/METRICS.md        (core/metrics_glossary.py)
#   - methods/<name>_model_card.md  (core/model_cards.py, one per
#                                    findings.json final method)

# Generic non-empty check (existence alone proves nothing for the
# deterministic v0.9.0 artifacts either).
verify_file_nonempty() {
  local desc="$1"; local path="$2"
  if [[ -s "$path" ]]; then ok "artifact non-empty: $desc"
  else fail "artifact missing/empty: $desc ($path)"
  fi
}

# reproduce.ipynb must exist AND be a structurally valid v4 notebook
# per nbformat.validate. nbformat is a core urika dependency as of
# v0.9.0 (pinned in pyproject), so no import gating is needed here.
verify_notebook_valid() {
  local desc="$1"; local path="$2"
  if [[ ! -f "$path" ]]; then
    fail "$desc — notebook missing: $path"
    return 1
  fi
  NB_PATH="$path" _verify_py "$desc" '
import os
import nbformat
nb = nbformat.read(os.environ["NB_PATH"], as_version=4)
nbformat.validate(nb)
'
}

# Execute reproduce.ipynb on a fresh kernel, from the project root
# (the notebook setup cell documents that working directory — the
# embedded method scripts use project-relative data paths). Gated on
# nbclient importability: nbclient is NOT a urika dependency, so skip
# cleanly when absent — unit tests + verify_notebook_valid still cover
# structural validity, only end-to-end execution is deferred.
verify_notebook_executes() {
  local desc="$1"; local path="$2"; local workdir="$3"
  if ! python3 -c "import nbclient" >/dev/null 2>&1; then
    log "▸ SKIP: $desc (nbclient not installed)"
    return 0
  fi
  if [[ ! -f "$path" ]]; then
    fail "$desc — notebook missing: $path"
    return 1
  fi
  NB_PATH="$path" NB_WORKDIR="$workdir" _verify_py "$desc" '
import os
import nbclient
import nbformat
nb = nbformat.read(os.environ["NB_PATH"], as_version=4)
nbclient.NotebookClient(
    nb,
    timeout=600,
    kernel_name="python3",
    resources={"metadata": {"path": os.environ["NB_WORKDIR"]}},
).execute()
'
}

# At least one model card must have been written with real content.
# (One card per findings.json final method; the smoke already asserts
# findings.json names >=1 final method, so zero cards means the
# finalize hook silently failed.)
verify_model_cards_present() {
  local desc="$1"; local proj_dir="$2"
  local found=0 card
  for card in "$proj_dir"/methods/*_model_card.md; do
    [[ -s "$card" ]] && found=$((found+1))
  done
  if (( found >= 1 )); then
    ok "$desc (${found} card(s))"
  else
    fail "$desc — no non-empty methods/*_model_card.md in $proj_dir"
  fi
}

# Diagnostic figures must have been produced by the task agent. A run
# that reports metrics but never draws a plot is "incomplete" per the
# task_agent prompt — surface that.
verify_figures_produced() {
  local desc="$1"; local proj_dir="$2"
  PROJ_DIR="$proj_dir" _verify_py "$desc" '
import os, sys, glob
proj = os.environ["PROJ_DIR"]
figs = []
for pat in ("*.png", "*.svg", "*.jpg", "*.jpeg", "*.pdf"):
    figs += glob.glob(os.path.join(proj, "experiments", "*", "artifacts", "**", pat), recursive=True)
    figs += glob.glob(os.path.join(proj, "experiments", "*", "artifacts", pat))
if not figs:
    print(f"  no figures under any experiments/*/artifacts/ in {proj}", file=sys.stderr)
    sys.exit(1)
'
}

# Every experiment directory (not just the latest) must have recorded
# >=1 run. Use after `urika run --max-experiments N` so the meta-loop
# can'\''t pad the count with an experiment that was created then died
# on turn 1.
verify_each_experiment_did_work() {
  local desc="$1"; local proj_dir="$2"
  PROJ_DIR="$proj_dir" _verify_py "$desc" '
import json, os, sys
proj = os.environ["PROJ_DIR"]
expdir = os.path.join(proj, "experiments")
dirs = sorted(d for d in (os.listdir(expdir) if os.path.isdir(expdir) else []) if os.path.isdir(os.path.join(expdir, d)))
if not dirs:
    print(f"  no experiment directories in {proj}", file=sys.stderr); sys.exit(1)
bad = []
for d in dirs:
    pj = os.path.join(expdir, d, "progress.json")
    runs = json.load(open(pj)).get("runs", []) if os.path.exists(pj) else []
    if len(runs) < 1:
        bad.append(d)
if bad:
    print(f"  experiment dirs with 0 recorded runs: {bad}", file=sys.stderr); sys.exit(1)
'
}

# run.log for a step must NOT contain the *fatal* early-exit
# tell-tales: an experiment that failed on turn 1, that paused on
# turn 1 (a transient/unknown error before any progress — resumable,
# but the run did not advance), any "Experiment failed:" line, or an
# experiment that ran every turn but recorded zero runs. (A per-turn
# "produced no parseable run records / criteria assessment / method
# plan" *warning* is fine — that's the warning system working; the
# run-content checks above catch the case where it actually mattered.)
#
# ``no further experiments to suggest`` is intentionally OMITTED here:
# it's the advisor's NORMAL terminal signal when an autonomous run has
# explored the space adequately. Whether the run completed enough
# experiments to satisfy the smoke is already measured by the
# ``autonomous run started >=2 experiments`` assertion. Treating that
# string as fatal flagged runs that had already met their experiment-
# count goal as failures, which they aren't. Removed v0.5.0.2.
#
# Args: <desc> <logfile>.
verify_no_early_exit_markers() {
  local desc="$1"; local logfile="$2"
  if [[ ! -f "$logfile" ]]; then
    fail "$desc — log file missing: $logfile"
    return 1
  fi
  local hit
  hit="$(grep -m1 -iE 'failed after 1 turn|paused after turn 1\b|Experiment failed:|but recorded 0 runs' "$logfile" || true)"
  if [[ -n "$hit" ]]; then
    fail "$desc" "early-exit marker in log: $hit"
  else
    ok "$desc"
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
  echo "  TRANSIENT: $TRANSIENT"
  if (( TRANSIENT > 0 )); then
    echo "  note: $TRANSIENT step(s) failed for a transient API reason and"
    echo "        were tolerated (not release-blocking; exit code reflects FAIL only)."
  fi
  echo "  Logs: $URIKA_E2E_LOG_DIR/"
  echo "============================================================"
}
