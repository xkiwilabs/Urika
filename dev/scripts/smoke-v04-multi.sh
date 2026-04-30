#!/usr/bin/env bash
# Multi-dataset smoke: run new + status + memory + drift + delete on
# each of the 10 test datasets that have a stored CSV (skip the
# generated/synthetic ones to avoid the download dependency).

set -uo pipefail
SMOKE_DIR="$(mktemp -d -t urika-smoke-multi-XXXXXX)"
export URIKA_HOME="$SMOKE_DIR/home"
export URIKA_PROJECTS_DIR="$SMOKE_DIR/projects"
mkdir -p "$URIKA_HOME" "$URIKA_PROJECTS_DIR"

PASS=0
FAIL=0

ok() { echo "    PASS"; PASS=$((PASS+1)); }
fail() { echo "    FAIL: $1"; FAIL=$((FAIL+1)); }

declare -a DATASETS=(
  "stroop:dev/test-datasets/stroop/data/stroop.csv:Is there a Stroop interference effect?"
  "depression:dev/test-datasets/depression/data:Which factors predict depression severity?"
  "marketing:dev/test-datasets/marketing/data:What customer segments exist?"
  "housing:dev/test-datasets/housing/data:Which features predict housing prices?"
  "climate:dev/test-datasets/climate/data:What predicts CO2 emissions per capita?"
)

for entry in "${DATASETS[@]}"; do
  name="${entry%%:*}"
  rest="${entry#*:}"
  data_path="${rest%%:*}"
  question="${rest#*:}"
  proj="smoke-04-$name"

  if [[ ! -e "$data_path" ]]; then
    echo "[$name] SKIP — data path missing: $data_path"
    continue
  fi

  echo
  echo "[$name] new + status + memory + drift + delete"
  echo "  data: $data_path"

  # 1. new
  echo -n "  new... "
  if urika new "$proj" --json --data "$data_path" \
      --question "$question" --description "smoke test" \
      --mode exploratory --privacy-mode open >/dev/null 2>&1; then
    ok
  else
    fail "new failed"; continue
  fi

  proj_dir="$URIKA_PROJECTS_DIR/$proj"

  # 2. status with data_hashes recorded
  echo -n "  status... "
  if urika status "$proj" --json | grep -q "data_drift"; then
    ok
  else
    fail "status missing data_drift"
  fi

  # 3. memory round-trip
  echo -n "  memory add+list... "
  echo "Test instruction for $name" | urika memory add "$proj" smoke_$name --type instruction --stdin >/dev/null 2>&1
  if urika memory list "$proj" --json | grep -q "smoke_$name"; then
    ok
  else
    fail "memory entry missing"
  fi

  # 4. delete
  echo -n "  delete... "
  if urika delete "$proj" --force >/dev/null 2>&1 && [[ ! -d "$proj_dir" ]]; then
    ok
  else
    fail "delete failed"
  fi
done

echo
echo "============================================================"
echo "Multi-dataset smoke summary:"
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo "============================================================"
rm -rf "$SMOKE_DIR"
exit $FAIL
