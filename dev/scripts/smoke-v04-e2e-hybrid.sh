#!/usr/bin/env bash
# End-to-end smoke for v0.4 in HYBRID privacy mode.
#
# Hybrid = data-handling agents (data_agent, tool_builder) run on the
# user's private endpoint while the strategic agents (planning,
# advisor, evaluator, report, presentation, finalizer) hit the open
# Anthropic API. Designed for projects whose raw data is sensitive
# (PII, customer records, etc.) but whose narrative output is fine to
# generate via the open model.
#
# Drives the full Urika pipeline against the marketing dataset
# (synthetic customer segmentation data).
#
# Usage:
#   bash dev/scripts/smoke-v04-e2e-hybrid.sh             # leave project for inspection
#   bash dev/scripts/smoke-v04-e2e-hybrid.sh --cleanup   # delete project on success
#
# Prereqs:
#   - urika installed and on PATH
#   - ANTHROPIC_API_KEY exported OR ~/.urika/secrets.env contains one
#   - At least one private endpoint configured in
#     ~/.urika/settings.toml under [privacy.endpoints], with its
#     api_key_env variable populated.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/smoke-v04-e2e-common.sh"

DATASET="$SCRIPT_DIR/../test-datasets/marketing/data/customer_segmentation.csv"
TS="$(date +%Y%m%d-%H%M%S)"
PROJ="e2e-hybrid-marketing-${TS}"
PROJ_DIR="$HOME/urika-projects/$PROJ"
QUESTION="What natural customer segments exist based on demographic and behavioral features, and how can each segment be characterized?"
DESCRIPTION="E2E smoke (hybrid mode) — synthetic CRM data; data agents on private endpoint, narrative agents on open API."

CLEANUP="${1:-}"

echo "======================================================================"
echo "v0.4 E2E SMOKE — HYBRID MODE"
echo "  project:    $PROJ"
echo "  data:       $DATASET"
echo "  proj dir:   $PROJ_DIR"
echo "  log dir:    $URIKA_E2E_LOG_DIR"
echo "  cleanup:    ${CLEANUP:-no}"
echo "  config:     ${URIKA_SMOKE_MODE_LABEL}"
echo "  max-turns:  ${URIKA_SMOKE_MAX_TURNS_HYBRID}"
echo "======================================================================"

# === Pre-flight ======================================================
if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && \
   ! { [[ -f "$HOME/.urika/secrets.env" ]] && grep -q "^ANTHROPIC_API_KEY=" "$HOME/.urika/secrets.env"; }; then
  echo
  echo "FATAL: hybrid mode still calls the open API for narrative agents."
  echo "       Set ANTHROPIC_API_KEY or run 'urika config api-key' first."
  exit 2
fi

# Hybrid additionally needs at least one private endpoint configured.
HAS_PRIVATE="$(python3 - <<'PY' 2>/dev/null
import sys
try:
    from urika.core.settings import get_named_endpoints
except Exception:
    print("0"); sys.exit(0)
print("1" if get_named_endpoints() else "0")
PY
)"
if [[ "$HAS_PRIVATE" != "1" ]]; then
  echo
  echo "FATAL: hybrid mode requires a configured private endpoint."
  echo "       Run 'urika config' and add one under [privacy.endpoints]."
  exit 2
fi

# === 1. urika new ====================================================
step "1. urika new (hybrid mode)"
if run_step_with_timeout "urika new" 180 \
     urika new "$PROJ" --json --data "$DATASET" \
       --question "$QUESTION" \
       --description "$DESCRIPTION" \
       --mode exploratory \
       --privacy-mode hybrid; then
  verify_artifact "project urika.toml" "$PROJ_DIR/urika.toml"
  verify_artifact_contains "privacy_mode = \"hybrid\"" "$PROJ_DIR/urika.toml" "hybrid"
  verify_artifact_contains "data_hashes recorded" "$PROJ_DIR/urika.toml" "data_hashes"
  verify_artifact "criteria.json" "$PROJ_DIR/criteria.json"
  verify_artifact "data dir" "$PROJ_DIR/data"

  # v0.4.3 Track 2d: cheap-config model overrides (no-op when
  # URIKA_SMOKE_REAL=1). Note that hybrid mode's data agent is
  # already on the private endpoint via global settings; this
  # only retunes the cloud-bound agents to sonnet for cost.
  inject_cheap_models "$PROJ_DIR"
fi

# === 2. status / inspect =============================================
step "2. status / inspect"
run_step_with_timeout "status --json" 30 urika status "$PROJ" --json
run_step_with_timeout "inspect --json" 30 urika inspect "$PROJ" --json

# === 3. advisor (open API) ===========================================
step "3. urika advisor (open API in hybrid)"
run_step_with_timeout "advisor" 180 \
  urika advisor "$PROJ" "What clustering approach would you start with for unsupervised customer segmentation?"

# === 4. build-tool (private endpoint in hybrid) ======================
step "4. urika build-tool (private endpoint in hybrid)"
if run_step_with_timeout "build-tool" 600 \
     urika build-tool "$PROJ" \
       "create a tool called segment_profile that takes a cluster label column and returns per-cluster mean/SD for numeric features and mode for categorical features"
then
  verify_artifact "tools/ dir present" "$PROJ_DIR/tools"
fi

# === 5. plan =========================================================
# Skipped — `urika plan` requires an existing experiment; the
# orchestrator invokes the planning_agent internally during run.

# === 6. run — single experiment ======================================
# Hybrid mode hits the network for every private-endpoint agent call,
# so 5 turns + reports + presentation can comfortably exceed the
# pre-v0.4.1 50-min budget. Bumped to 90 min — the timeout still
# guards against true wedges but stops misclassifying legit-but-slow
# hybrid runs as failures (the v0.4.1 #3 fix means the
# `keeping completed status` branch is the right outcome when this
# does fire).
step "6. urika run --max-turns ${URIKA_SMOKE_MAX_TURNS_HYBRID}"
if run_step_with_timeout "run experiment 1" 5400 \
     urika run "$PROJ" --max-turns ${URIKA_SMOKE_MAX_TURNS_HYBRID} --auto -q
then
  verify_artifact "experiments/ dir" "$PROJ_DIR/experiments"
fi

# === 7. autonomous mode ==============================================
step "7. urika run --max-experiments 2 --budget 3.00"
run_step_with_timeout "autonomous 2 experiments" 5400 \
  urika run "$PROJ" --max-experiments 2 --max-turns ${URIKA_SMOKE_MAX_TURNS_HYBRID} --budget 3.00 --auto -q

# === 8. evaluate =====================================================
step "8. urika evaluate (latest experiment)"
LATEST_EXP="$(urika experiment list "$PROJ" 2>/dev/null \
               | awk 'NF>0 && $1 ~ /^exp-/ {last=$1} END {print last}')"
log "Latest experiment: ${LATEST_EXP:-<none>}"
if [[ -n "$LATEST_EXP" ]]; then
  run_step_with_timeout "evaluate" 600 urika evaluate "$PROJ" "$LATEST_EXP"
else
  fail "evaluate skipped — could not resolve experiment ID"
fi

# === 9. report =======================================================
step "9. urika report"
if run_step_with_timeout "report" 600 urika report "$PROJ"; then
  verify_artifact "projectbook/key-findings.md" "$PROJ_DIR/projectbook/key-findings.md"
  verify_artifact "projectbook/results-summary.md" "$PROJ_DIR/projectbook/results-summary.md"
fi

# === 10. present =====================================================
# Project-level decks land under either ``projectbook/presentation/``
# (legacy / agent-default) or ``projectbook/final-presentation/``
# (v0.4.0+ finalize rename). Accept either.
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

# === 11. finalize ====================================================
step "11. urika finalize"
if run_step_with_timeout "finalize" 1500 urika finalize "$PROJ"; then
  verify_artifact "projectbook/findings.json"  "$PROJ_DIR/projectbook/findings.json"
  verify_artifact "requirements.txt"           "$PROJ_DIR/requirements.txt"
  verify_artifact "reproduce.sh"               "$PROJ_DIR/reproduce.sh"
  verify_artifact "README.md"                  "$PROJ_DIR/README.md"
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
