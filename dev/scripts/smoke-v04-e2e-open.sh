#!/usr/bin/env bash
# End-to-end smoke for v0.4 in OPEN privacy mode.
#
# Drives the full Urika pipeline against the small Stroop dataset
# using real Anthropic API calls (claude-opus-4-6). Project lives
# under the user's real ~/urika-projects/ so it shows up in the
# dashboard for visual inspection.
#
# Usage:
#   bash dev/scripts/smoke-v04-e2e-open.sh                     # leave project for inspection
#   bash dev/scripts/smoke-v04-e2e-open.sh --cleanup           # delete project on success
#
# v0.7.0 multi-provider modes (Task 4.5):
#   bash dev/scripts/smoke-v04-e2e-open.sh --provider anthropic
#   bash dev/scripts/smoke-v04-e2e-open.sh --provider openai
#   bash dev/scripts/smoke-v04-e2e-open.sh --provider google
#   bash dev/scripts/smoke-v04-e2e-open.sh --mixed-providers
#   bash dev/scripts/smoke-v04-e2e-open.sh --provider anthropic --anthropic-auth subscription
#
# Flags can be combined freely (e.g. ``--provider openai --cleanup``).
#
# Prereqs:
#   - urika installed and on PATH
#   - For --provider anthropic: ANTHROPIC_API_KEY in env or ~/.urika/secrets.env
#     (or, with --anthropic-auth subscription, ``claude login`` completed)
#   - For --provider openai: OPENAI_API_KEY in env or vault
#   - For --provider google: GOOGLE_API_KEY (or GEMINI_API_KEY) in env or vault
#   - For --mixed-providers: all three keys above
#
# This script will take 30-60 minutes (real LLM round-trips at every
# stage). Per-step output goes to dev/scripts/.smoke-logs/<ts>-<pid>/.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/smoke-v04-e2e-common.sh"

DATASET="$SCRIPT_DIR/../test-datasets/stroop/data/stroop.csv"
TS="$(date +%Y%m%d-%H%M%S)"
PROJ="e2e-open-stroop-${TS}"
PROJ_DIR="$HOME/urika-projects/$PROJ"
QUESTION="Is there a statistically significant Stroop interference effect, and what is the effect size?"
DESCRIPTION="E2E smoke (open mode) — Stroop reaction-time data, paired-difference confirmatory test."

# v0.7.0 Task 4.5: flag parsing. Order-independent; everything is
# optional. Backward-compat: a lone ``--cleanup`` (the CI invocation)
# still works exactly as before.
PROVIDER="${PROVIDER:-anthropic}"
MIXED_PROVIDERS=0
ANTHROPIC_AUTH="${ANTHROPIC_AUTH:-api_key}"
CLEANUP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --mixed-providers) MIXED_PROVIDERS=1; shift ;;
    --anthropic-auth) ANTHROPIC_AUTH="$2"; shift 2 ;;
    --cleanup) CLEANUP="--cleanup"; shift ;;
    *) break ;;
  esac
done

# Validate
case "$PROVIDER" in
  anthropic|openai|google) ;;
  *) echo "FATAL: --provider must be one of: anthropic, openai, google (got: $PROVIDER)" >&2; exit 2 ;;
esac
case "$ANTHROPIC_AUTH" in
  api_key|subscription) ;;
  *) echo "FATAL: --anthropic-auth must be one of: api_key, subscription (got: $ANTHROPIC_AUTH)" >&2; exit 2 ;;
esac

if (( MIXED_PROVIDERS == 1 )); then
  MODE_LINE="MIXED (planner=anthropic, task=openai, advisor=google)"
else
  MODE_LINE="${PROVIDER}"
  if [[ "$PROVIDER" == "anthropic" ]]; then
    MODE_LINE="${MODE_LINE} (auth=${ANTHROPIC_AUTH})"
  fi
fi

echo "======================================================================"
echo "v0.4 E2E SMOKE — OPEN MODE"
echo "  project:    $PROJ"
echo "  data:       $DATASET"
echo "  proj dir:   $PROJ_DIR"
echo "  log dir:    $URIKA_E2E_LOG_DIR"
echo "  cleanup:    ${CLEANUP:-no}"
echo "  config:     ${URIKA_SMOKE_MODE_LABEL}"
echo "  max-turns:  ${URIKA_SMOKE_MAX_TURNS_OPEN}"
echo "  providers:  ${MODE_LINE}"
echo "======================================================================"

# === Pre-flight: API key present =====================================
# Required keys depend on which provider(s) the run will use. Anthropic
# subscription mode (``--anthropic-auth subscription``) is the only
# path that doesn't need ANTHROPIC_API_KEY — it relies on a prior
# ``claude login``, so we don't probe it here.
_check_env_or_secrets() {
  local key="$1"
  if [[ -n "${!key:-}" ]]; then return 0; fi
  if [[ -f "$HOME/.urika/secrets.env" ]] && grep -q "^${key}=" "$HOME/.urika/secrets.env"; then
    return 0
  fi
  return 1
}

REQUIRED_KEYS=()
if (( MIXED_PROVIDERS == 1 )); then
  REQUIRED_KEYS+=(ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY)
else
  case "$PROVIDER" in
    anthropic)
      if [[ "$ANTHROPIC_AUTH" == "api_key" ]]; then
        REQUIRED_KEYS+=(ANTHROPIC_API_KEY)
      fi
      ;;
    openai) REQUIRED_KEYS+=(OPENAI_API_KEY) ;;
    google) REQUIRED_KEYS+=(GOOGLE_API_KEY) ;;
  esac
fi

for key in "${REQUIRED_KEYS[@]}"; do
  if ! _check_env_or_secrets "$key"; then
    # GOOGLE_API_KEY / GEMINI_API_KEY are interchangeable for Gemini.
    if [[ "$key" == "GOOGLE_API_KEY" ]] && _check_env_or_secrets GEMINI_API_KEY; then
      continue
    fi
    echo
    echo "FATAL: open mode (providers=${MODE_LINE}) requires ${key} in env or ~/.urika/secrets.env."
    exit 2
  fi
done

# === 1. urika new ====================================================
step "1. urika new (open mode)"
if run_step_with_timeout "urika new" 180 \
     urika new "$PROJ" --json --data "$DATASET" \
       --question "$QUESTION" \
       --description "$DESCRIPTION" \
       --mode confirmatory \
       --privacy-mode open; then
  verify_artifact "project urika.toml" "$PROJ_DIR/urika.toml"
  verify_artifact_contains "data_hashes recorded" "$PROJ_DIR/urika.toml" "data_hashes"
  verify_artifact "criteria.json" "$PROJ_DIR/criteria.json"
  verify_artifact "data dir" "$PROJ_DIR/data"
  verify_artifact "projectbook dir" "$PROJ_DIR/projectbook"

  # v0.7.0 Task 4.5: provider-driven model selection takes precedence
  # over the cheap-config injection. When the operator explicitly picks
  # a non-Anthropic provider, or asks for the mixed mode, we want the
  # smoke to exercise THOSE adapters with their default models — the
  # cheap-config (sonnet+haiku) is Anthropic-only and would defeat the
  # purpose. When the operator runs the default (or ``--provider
  # anthropic`` without overrides), fall back to the existing cheap
  # path so the dev-loop cost stays low.
  if (( MIXED_PROVIDERS == 1 )); then
    inject_provider_models "$PROJ_DIR" "__mixed__"
  elif [[ "$PROVIDER" != "anthropic" ]]; then
    inject_provider_models "$PROJ_DIR" "$PROVIDER"
  else
    # v0.4.3 Track 2d: pin per-agent models cheaply for default smoke
    # runs. No-op when URIKA_SMOKE_REAL=1 (pre-release validation
    # uses the global config — typically opus + sonnet).
    inject_cheap_models "$PROJ_DIR"
  fi
fi

# v0.7.0 Task 4.5: subscription-mode preflight. Switches the
# Anthropic adapter to use the bundled ``claude`` CLI (no API key,
# no metered cost). The operator must have already run
# ``claude login`` for this to work end-to-end. ``--no-verify``
# skips the live "ping the API" check (subscription mode has no
# equivalent for the bearer-token probe).
if [[ "$PROVIDER" == "anthropic" && "$ANTHROPIC_AUTH" == "subscription" ]]; then
  step "0b. urika config anthropic --mode subscription"
  run_step_with_timeout "config anthropic subscription" 30 \
    urika config anthropic --mode subscription --no-verify
fi

# === 2. urika status & inspect (read-only sanity) ====================
step "2. status / inspect"
run_step_with_timeout "status --json" 30 urika status "$PROJ" --json
run_step_with_timeout "inspect --json" 30 urika inspect "$PROJ" --json

# === 3. urika advisor (live LLM) =====================================
step "3. urika advisor (real LLM)"
run_step_with_timeout "advisor first turn" 180 \
  urika advisor "$PROJ" "What single analytical approach would you recommend first, and why?"

# === 4. urika build-tool =============================================
step "4. urika build-tool — paired-difference helper"
if run_step_with_timeout "build-tool" 360 \
     urika build-tool "$PROJ" \
       "create a tool called paired_diff_summary that takes two columns and returns the mean, SD, and 95% CI of the differences"
then
  verify_artifact "tools/ dir present" "$PROJ_DIR/tools"
fi

# === 5. urika plan ===================================================
# Skipped — `urika plan` requires an existing experiment to plan
# *for*, and at this point the project has none. The orchestrator
# invokes the planning_agent internally as part of `urika run`, so
# we rely on step 6 below for planning coverage.

# === 6. urika run — single experiment, capped turns ==================
# 2700s = 45 min covers the full path: 5 turns of agents + the
# orchestrator's post-criteria finalize sequence (which runs both
# experiment-level AND project-level narrative agents — the project
# narrative routinely takes 10-15 min on cloud models).
step "6. urika run --max-turns ${URIKA_SMOKE_MAX_TURNS_OPEN} (single experiment)"
if run_step_with_timeout "run experiment 1" 2700 \
     urika run "$PROJ" --max-turns ${URIKA_SMOKE_MAX_TURNS_OPEN} --auto -q
then
  verify_artifact "experiments/ dir" "$PROJ_DIR/experiments"
  verify_artifact "leaderboard.json" "$PROJ_DIR/leaderboard.json"
  verify_run_did_work "run experiment 1 recorded >=1 run + non-empty leaderboard" "$PROJ_DIR"
  verify_run_metrics_nonempty "run experiment 1 — >=1 run has non-empty metrics" "$PROJ_DIR"
  verify_turns_ran "run experiment 1 ran >=1 loop turn" "$PROJ_DIR" 1
  verify_methods_consistent "methods.json <-> progress.json <-> leaderboard consistent" "$PROJ_DIR"
  verify_figures_produced "run experiment 1 produced >=1 diagnostic figure" "$PROJ_DIR"
  verify_no_early_exit_markers "run experiment 1 — no early-exit markers in log" \
    "$URIKA_E2E_LOG_DIR/run_experiment_1.log"
fi

# Capture first experiment ID for later evaluate / present steps.
FIRST_EXP="$(urika experiment list "$PROJ" 2>/dev/null \
              | awk 'NF>0 && $1 ~ /^exp-/ {print $1; exit}')"
log "First experiment: ${FIRST_EXP:-<none>}"

# === 7. urika run --max-experiments 2 (autonomous) ===================
# 4800s = 80 min: two experiments × ~30 min each + finalize
# overhead. Budget gate (2.00 USD) will pause the run earlier on
# Anthropic open mode; for slower endpoints this gives headroom.
step "7. urika run --max-experiments 2 --budget 2.00"
if run_step_with_timeout "autonomous 2 experiments" 4800 \
     urika run "$PROJ" --max-experiments 2 --max-turns ${URIKA_SMOKE_MAX_TURNS_OPEN} --budget 2.00 --auto -q
then
  # The budget gate (2.00 USD) may legitimately pause before the 2nd
  # experiment finishes — but the meta loop must at least *start* a
  # second experiment. "0 or 1 experiment dirs after --max-experiments 2"
  # is the advisor-parse-miss bail (HIGH-3), not a budget pause.
  verify_min_experiments "autonomous run started >=2 experiments" "$PROJ_DIR" 2 \
    "$URIKA_E2E_LOG_DIR/autonomous_2_experiments.log"
  verify_each_experiment_did_work "every experiment recorded >=1 run" "$PROJ_DIR"
  verify_methods_consistent "methods/leaderboard still consistent after 2 experiments" "$PROJ_DIR"
  verify_no_early_exit_markers "autonomous run — no early-exit markers in log" \
    "$URIKA_E2E_LOG_DIR/autonomous_2_experiments.log"
fi

# === 8. urika evaluate ===============================================
step "8. urika evaluate (latest experiment)"
LATEST_EXP="$(urika experiment list "$PROJ" 2>/dev/null \
               | awk 'NF>0 && $1 ~ /^exp-/ {last=$1} END {print last}')"
log "Latest experiment: ${LATEST_EXP:-<none>}"
if [[ -n "$LATEST_EXP" ]]; then
  run_step_with_timeout "evaluate" 600 \
    urika evaluate "$PROJ" "$LATEST_EXP"
else
  fail "evaluate skipped — could not resolve experiment ID"
fi

# === 9. urika report =================================================
# `urika report` (project-level) writes key-findings.md and
# results-summary.md to projectbook/. The agent-written narrative.md
# is produced by the orchestrator's post-criteria finalize sequence
# during `urika run`, not by `urika report` itself.
step "9. urika report (project-level)"
if run_step_with_timeout "report" 600 urika report "$PROJ"; then
  verify_artifact "projectbook/key-findings.md" "$PROJ_DIR/projectbook/key-findings.md"
  verify_artifact "projectbook/results-summary.md" "$PROJ_DIR/projectbook/results-summary.md"
fi

# === 9b. urika report --format latex (v0.9.0, pandoc-gated) ==========
# Exercises the pypandoc/pandoc export path end-to-end: re-runs the
# report agent for the latest experiment and post-processes the
# narrative it writes into labbook/narrative.tex. Gated on BOTH the
# pypandoc package (the urika[export] extra) and a pandoc binary on
# PATH — when either is absent the export path raises a deliberate
# actionable ExportError (unit-tested in tests/test_core/test_export.py),
# so the smoke skips cleanly rather than asserting the failure mode.
step "9b. urika report --format latex (pandoc-gated)"
if python3 -c "import pypandoc" >/dev/null 2>&1 \
     && command -v pandoc >/dev/null 2>&1; then
  if [[ -n "${LATEST_EXP:-}" ]]; then
    if run_step_with_timeout "report latex" 600 \
         urika report "$PROJ" --experiment "$LATEST_EXP" --format latex
    then
      verify_artifact_contains "narrative.tex is a standalone LaTeX doc" \
        "$PROJ_DIR/experiments/$LATEST_EXP/labbook/narrative.tex" \
        '\\documentclass'
    fi
  else
    fail "report latex skipped — could not resolve experiment ID"
  fi
else
  log "▸ SKIP: LaTeX export check (pypandoc and/or pandoc binary not available)"
fi

# === 10. urika present (project-level) ===============================
step "10. urika present --experiment project"
if run_step_with_timeout "present project" 900 \
     urika present "$PROJ" --experiment project
then
  verify_artifact_any "presentation dir" \
    "$PROJ_DIR/projectbook/presentation" \
    "$PROJ_DIR/projectbook/final-presentation"
  verify_artifact_any "presentation index.html" \
    "$PROJ_DIR/projectbook/presentation/index.html" \
    "$PROJ_DIR/projectbook/final-presentation/index.html"
fi

# === 11. urika finalize ==============================================
# Required finalize outputs (always written):
#   - findings.json    -> projectbook/findings.json
#   - requirements.txt -> project root
#   - reproduce.sh     -> project root
#   - README.md        -> project root (regenerated from findings)
#
# final-report.md (projectbook/final-report.md) is best-effort: the
# orchestrator writes it only when the report agent's output meets a
# heading / length threshold. If the agent burns its turns trying to
# Write the file directly (it has no write tools — read-only role),
# the orchestrator falls back to "report generated" without writing.
# This is a known issue tracked for a follow-up release; the
# narrative.md from the post-criteria sequence is the authoritative
# project narrative.
step "11. urika finalize"
if run_step_with_timeout "finalize" 1500 urika finalize "$PROJ"; then
  verify_artifact "projectbook/findings.json"  "$PROJ_DIR/projectbook/findings.json"
  verify_findings_nonempty "findings.json has an answer + >=1 final method" "$PROJ_DIR/projectbook/findings.json"
  verify_artifact "requirements.txt"           "$PROJ_DIR/requirements.txt"
  verify_artifact "reproduce.sh"               "$PROJ_DIR/reproduce.sh"
  verify_artifact "README.md"                  "$PROJ_DIR/README.md"
  # Content checks (and, under URIKA_SMOKE_REAL, an actual venv install)
  # — these are the only guard on the agent-written reproducibility
  # artifacts; existence alone proves nothing.
  verify_finalize_artifacts_real "finalize reproducibility artifacts" "$PROJ_DIR"
  # v0.9.0 output-polish artifacts — written by finalize's best-effort
  # hooks (orchestrator/finalize.py), so a silent hook failure only
  # shows up here.
  verify_notebook_valid "projectbook/reproduce.ipynb validates (nbformat)" \
    "$PROJ_DIR/projectbook/reproduce.ipynb"
  verify_notebook_executes "reproduce.ipynb executes on a fresh kernel" \
    "$PROJ_DIR/projectbook/reproduce.ipynb" "$PROJ_DIR"
  verify_file_nonempty "projectbook/METRICS.md" "$PROJ_DIR/projectbook/METRICS.md"
  verify_model_cards_present ">=1 model card written" "$PROJ_DIR"
fi

# === 12. Cleanup (optional) ==========================================
if [[ "$CLEANUP" == "--cleanup" ]] && (( FAIL == 0 )); then
  step "cleanup"
  if urika delete "$PROJ" --force > /dev/null 2>&1; then
    ok "project deleted"
  else
    fail "delete failed"
  fi
fi

print_summary
exit $FAIL
