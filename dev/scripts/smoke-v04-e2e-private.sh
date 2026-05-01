#!/usr/bin/env bash
# End-to-end smoke for v0.4 in PRIVATE privacy mode.
#
# Private = every agent runs against the user's configured private
# endpoint (e.g. a local vLLM / Ollama / TGI deployment). No data is
# sent to Anthropic. Drives the full Urika pipeline against the
# Depression-survey dataset (500 rows × 10 columns) — clinical
# screening data is the canonical "this is why private mode exists"
# use case. Different code paths from the Stroop paired-t-test
# (open-mode dataset) and the Marketing clustering (hybrid-mode
# dataset): regression / feature-importance for a continuous
# clinical score.
#
# Usage:
#   bash dev/scripts/smoke-v04-e2e-private.sh             # leave project for inspection
#   bash dev/scripts/smoke-v04-e2e-private.sh --cleanup   # delete project on success
#
# Prereqs:
#   - urika installed and on PATH
#   - At least one private endpoint configured in
#     ~/.urika/settings.toml under [privacy.endpoints]
#   - The endpoint's api_key_env variable populated in the env or
#     ~/.urika/secrets.env
#   - The endpoint actually reachable from this host

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/smoke-v04-e2e-common.sh"

DATASET="$SCRIPT_DIR/../test-datasets/depression/data/depression_survey.csv"
TS="$(date +%Y%m%d-%H%M%S)"
PROJ="e2e-private-depression-${TS}"
PROJ_DIR="$HOME/urika-projects/$PROJ"
QUESTION="Which modifiable lifestyle factors (sleep, exercise, social support, stress) are the strongest predictors of depression severity, and can we build a reliable predictive model for BDI score?"
DESCRIPTION="E2E smoke (private mode) — synthetic clinical depression survey, all agents on private endpoint."

CLEANUP="${1:-}"

echo "======================================================================"
echo "v0.4 E2E SMOKE — PRIVATE MODE"
echo "  project:    $PROJ"
echo "  data:       $DATASET"
echo "  proj dir:   $PROJ_DIR"
echo "  log dir:    $URIKA_E2E_LOG_DIR"
echo "  cleanup:    ${CLEANUP:-no}"
echo "======================================================================"

# === Pre-flight ======================================================
ENDPOINT_INFO="$(python3 - <<'PY' 2>/dev/null
import sys
try:
    from urika.core.settings import get_named_endpoints
except Exception as exc:
    print(f"ERROR: {exc}"); sys.exit(0)
eps = get_named_endpoints()
if not eps:
    print("NONE")
else:
    for ep in eps:
        print(f"{ep.get('name','?')}\t{ep.get('base_url','?')}\t{ep.get('api_key_env','?')}")
PY
)"

if [[ "$ENDPOINT_INFO" == "NONE" || -z "$ENDPOINT_INFO" || "$ENDPOINT_INFO" == ERROR:* ]]; then
  echo
  echo "FATAL: private mode requires a configured private endpoint."
  echo "       Run 'urika config' and add one under [privacy.endpoints]."
  echo "       (probe output: ${ENDPOINT_INFO:-<empty>})"
  exit 2
fi

echo "  Configured private endpoints:"
echo "$ENDPOINT_INFO" | while IFS=$'\t' read -r name url envvar; do
  echo "    - $name → $url (key env: \$$envvar)"
done

# Verify the api_key_env for at least one endpoint is populated
# (process env wins; fall back to the global SecretsVault).
HAS_KEY="$(python3 - <<'PY' 2>/dev/null
import os, sys
try:
    from urika.core.settings import get_named_endpoints
    from urika.core.vault import SecretsVault
except Exception:
    print("0"); sys.exit(0)
vault = SecretsVault()
for ep in get_named_endpoints():
    var = ep.get("api_key_env")
    if not var:
        continue
    if os.environ.get(var) or vault.get(var):
        print("1"); sys.exit(0)
print("0")
PY
)"
if [[ "$HAS_KEY" != "1" ]]; then
  echo
  echo "FATAL: no private endpoint has its api_key_env populated."
  echo "       Set it in the env or under 'urika config secret'."
  exit 2
fi

# === 1. urika new ====================================================
step "1. urika new (private mode)"
if run_step_with_timeout "urika new" 360 \
     urika new "$PROJ" --json --data "$DATASET" \
       --question "$QUESTION" \
       --description "$DESCRIPTION" \
       --mode exploratory \
       --privacy-mode private; then
  verify_artifact "project urika.toml" "$PROJ_DIR/urika.toml"
  verify_artifact_contains "privacy_mode = \"private\"" "$PROJ_DIR/urika.toml" "private"
  verify_artifact_contains "data_hashes recorded" "$PROJ_DIR/urika.toml" "data_hashes"
  verify_artifact "criteria.json" "$PROJ_DIR/criteria.json"
  verify_artifact "data dir" "$PROJ_DIR/data"
fi

# === 2. status / inspect =============================================
step "2. status / inspect"
run_step_with_timeout "status --json" 30 urika status "$PROJ" --json
run_step_with_timeout "inspect --json" 30 urika inspect "$PROJ" --json

# === 3. advisor (private) ============================================
step "3. urika advisor (private endpoint)"
run_step_with_timeout "advisor" 360 \
  urika advisor "$PROJ" "Which single regression or feature-importance approach would you start with to identify the strongest lifestyle predictors of BDI score?"

# === 4. build-tool (private) =========================================
step "4. urika build-tool (private endpoint)"
if run_step_with_timeout "build-tool" 720 \
     urika build-tool "$PROJ" \
       "create a tool called bdi_severity_summary that takes a numeric BDI column and a categorical severity column and returns mean BDI per severity bucket, count per bucket, and the cutoff thresholds it inferred"
then
  verify_artifact "tools/ dir present" "$PROJ_DIR/tools"
fi

# === 5. plan =========================================================
step "5. urika plan"
run_step_with_timeout "plan" 600 urika plan "$PROJ"

# === 6. run — single experiment ======================================
step "6. urika run --max-turns 5"
if run_step_with_timeout "run experiment 1" 2400 \
     urika run "$PROJ" --max-turns 5 --auto -q
then
  verify_artifact "experiments/ dir" "$PROJ_DIR/experiments"
fi

# === 7. autonomous mode ==============================================
step "7. urika run --max-experiments 2 (no $ budget cap on private)"
run_step_with_timeout "autonomous 2 experiments" 3600 \
  urika run "$PROJ" --max-experiments 2 --max-turns 5 --auto -q

# === 8. evaluate =====================================================
step "8. urika evaluate (latest experiment)"
LATEST_EXP="$(urika experiment list "$PROJ" 2>/dev/null \
               | awk 'NF>0 && $1 ~ /^exp-/ {last=$1} END {print last}')"
log "Latest experiment: ${LATEST_EXP:-<none>}"
if [[ -n "$LATEST_EXP" ]]; then
  run_step_with_timeout "evaluate" 900 urika evaluate "$PROJ" "$LATEST_EXP"
else
  fail "evaluate skipped — could not resolve experiment ID"
fi

# === 9. report =======================================================
step "9. urika report"
if run_step_with_timeout "report" 1200 urika report "$PROJ"; then
  verify_artifact "projectbook/narrative.md" "$PROJ_DIR/projectbook/narrative.md"
fi

# === 10. present =====================================================
step "10. urika present --experiment project"
if run_step_with_timeout "present project" 1200 \
     urika present "$PROJ" --experiment project
then
  verify_artifact "final-presentation dir" "$PROJ_DIR/projectbook/final-presentation"
fi

# === 11. finalize ====================================================
step "11. urika finalize"
if run_step_with_timeout "finalize" 2400 urika finalize "$PROJ"; then
  verify_artifact "findings.json"     "$PROJ_DIR/findings.json"
  verify_artifact "requirements.txt"  "$PROJ_DIR/requirements.txt"
  verify_artifact "reproduce.sh"      "$PROJ_DIR/reproduce.sh"
  verify_artifact "README.md"         "$PROJ_DIR/README.md"
  verify_artifact "final-report.md"   "$PROJ_DIR/projectbook/final-report.md"
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
