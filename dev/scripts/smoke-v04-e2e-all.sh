#!/usr/bin/env bash
# Master runner for the v0.4 end-to-end smoke suite.
#
# Runs each privacy-mode E2E sequentially (open → hybrid → private),
# aggregates results, and prints a combined summary. Each sub-script
# writes its own per-step logs under dev/scripts/.smoke-logs/.
#
# Usage:
#   bash dev/scripts/smoke-v04-e2e-all.sh                # leave projects for inspection
#   bash dev/scripts/smoke-v04-e2e-all.sh --cleanup      # delete projects on success
#   bash dev/scripts/smoke-v04-e2e-all.sh --skip-private # skip private (e.g. endpoint offline)
#   bash dev/scripts/smoke-v04-e2e-all.sh --only open    # run a single mode
#
# Wall-clock: each script can take 30-60 minutes depending on agent
# verbosity and (for private) endpoint speed. Plan accordingly.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLEANUP=""
SKIP_PRIVATE=0
ONLY=""

while (( $# > 0 )); do
  case "$1" in
    --cleanup)        CLEANUP="--cleanup" ;;
    --skip-private)   SKIP_PRIVATE=1 ;;
    --only)           ONLY="${2:-}"; shift ;;
    -h|--help)
      sed -n '1,/^$/{p}' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

# Single shared log dir for the whole suite.
TS="$(date +%Y%m%d-%H%M%S)"
export URIKA_E2E_LOG_DIR="$SCRIPT_DIR/.smoke-logs/${TS}-master-$$"
mkdir -p "$URIKA_E2E_LOG_DIR"

echo "######################################################################"
echo "# v0.4 E2E SMOKE SUITE"
echo "#   logs:    $URIKA_E2E_LOG_DIR"
echo "#   cleanup: ${CLEANUP:-no}"
echo "#   only:    ${ONLY:-<all>}"
echo "######################################################################"

declare -a SUITE_RESULTS=()
SUITE_FAIL=0

run_mode() {
  local mode="$1"; shift
  local script="$SCRIPT_DIR/smoke-v04-e2e-${mode}.sh"
  if [[ ! -x "$script" ]]; then chmod +x "$script" 2>/dev/null || true; fi
  echo
  echo "######################################################################"
  echo "# RUNNING: $mode"
  echo "######################################################################"
  if bash "$script" $CLEANUP; then
    SUITE_RESULTS+=("PASS  e2e $mode")
  else
    SUITE_RESULTS+=("FAIL  e2e $mode (exit $?)")
    SUITE_FAIL=$((SUITE_FAIL+1))
  fi
}

if [[ -n "$ONLY" ]]; then
  case "$ONLY" in
    open|hybrid|private) run_mode "$ONLY" ;;
    *) echo "--only must be one of: open, hybrid, private"; exit 2 ;;
  esac
else
  run_mode "open"
  run_mode "hybrid"
  if (( SKIP_PRIVATE == 0 )); then
    run_mode "private"
  else
    SUITE_RESULTS+=("SKIP  e2e private (--skip-private)")
  fi
fi

echo
echo "######################################################################"
echo "# SUITE SUMMARY"
echo "######################################################################"
for r in "${SUITE_RESULTS[@]}"; do echo "  $r"; done
echo "----------------------------------------------------------------------"
echo "  Logs: $URIKA_E2E_LOG_DIR/"
echo "######################################################################"

exit $SUITE_FAIL
