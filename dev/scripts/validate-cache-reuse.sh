#!/usr/bin/env bash
# v0.4.3 cache-reuse validation: smallest meaningful real-API run that
# captures the cross-experiment cache delta the structural tests
# (tests/test_agents/test_prompt_cache_stability.py) predict.
#
# Setup:
#   - Cheap config (sonnet for reasoning, haiku elsewhere)
#   - Stroop dataset (132 rows, fast loads)
#   - 2 experiments × 2 turns each, $0.50 budget cap
#   - Captures URIKA_PROMPT_TRACE_FILE for per-call cache numbers
#
# Expected total cost: ~$0.10–$0.30. Total runtime: ~3–5 minutes.
#
# Reports:
#   - Per-agent cache_read / total_input ratio
#   - Cross-experiment delta: turn-1 of exp-2 vs turn-1 of exp-1
#   - System-prompt size stability (should be byte-identical across
#     experiments for a given role)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET="$SCRIPT_DIR/../test-datasets/stroop/data/stroop.csv"
TS="$(date +%Y%m%d-%H%M%S)"
PROJ="cache-validation-${TS}"
PROJ_DIR="$HOME/urika-projects/$PROJ"
TRACE_FILE="/tmp/urika-cache-validation-${TS}.jsonl"

export URIKA_PROMPT_TRACE_FILE="$TRACE_FILE"
# Force cheap-config models (matches smoke-v04-e2e-common.sh defaults
# but we need them set for the run subprocess).
unset URIKA_SMOKE_REAL

echo "======================================================================"
echo "v0.4.3 CACHE-REUSE VALIDATION"
echo "  project:    $PROJ"
echo "  data:       $DATASET (Stroop, 132 rows)"
echo "  trace:      $TRACE_FILE"
echo "  budget:     \$0.50 cap"
echo "  config:     2 experiments × 2 turns, sonnet + haiku"
echo "======================================================================"

if [[ ! -f "$DATASET" ]]; then
  echo "FATAL: dataset not found at $DATASET"
  exit 2
fi

# Step 1: create project (no LLM cost — config-only)
echo
echo "[1/3] Creating project..."
urika new "$PROJ" --json --data "$DATASET" \
  --question "Is there a Stroop interference effect, and what is its size?" \
  --description "Cache-reuse validation run." \
  --mode confirmatory \
  --privacy-mode open >/dev/null

if [[ ! -f "$PROJ_DIR/urika.toml" ]]; then
  echo "FATAL: project not created at $PROJ_DIR"
  exit 2
fi

# Inject cheap-config models (sonnet for reasoning, default haiku
# elsewhere). Mirrors inject_cheap_models() in smoke-v04-e2e-common.sh.
cat >> "$PROJ_DIR/urika.toml" <<'EOF'

[runtime.models.planning_agent]
model = "claude-sonnet-4-5"

[runtime.models.advisor_agent]
model = "claude-sonnet-4-5"

[runtime.models.evaluator]
model = "claude-sonnet-4-5"

[runtime.models.task_agent]
model = "claude-haiku-4-5"

[runtime.models.data_agent]
model = "claude-haiku-4-5"

[runtime.models.tool_builder]
model = "claude-haiku-4-5"
EOF

echo "    project ready: $PROJ_DIR"

# Step 2: autonomous mode, 2 experiments × 2 turns, hard budget cap
echo
echo "[2/3] Running 2 experiments × 2 turns (autonomous)..."
echo "    Watch live: tail -f $URIKA_PROMPT_TRACE_FILE"
START_TS=$(date +%s)
urika run "$PROJ" \
  --max-experiments 2 \
  --max-turns 2 \
  --budget 0.50 \
  --auto -q || true   # don't bail on non-zero exit (budget pause is OK)
ELAPSED=$(($(date +%s) - START_TS))
echo "    elapsed: ${ELAPSED}s"

# Step 3: parse the trace + report
echo
echo "[3/3] Parsing trace..."
if [[ ! -s "$TRACE_FILE" ]]; then
  echo "FATAL: trace file is empty — caching events weren't recorded"
  exit 3
fi

python3 "$SCRIPT_DIR/parse-cache-trace.py" "$TRACE_FILE"

echo
echo "======================================================================"
echo "DONE. Project kept at $PROJ_DIR (use 'urika delete $PROJ --force' to drop)."
echo "Trace kept at $TRACE_FILE."
echo "======================================================================"
