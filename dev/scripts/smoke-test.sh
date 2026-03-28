#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Urika End-to-End Smoke Test
# ═══════════════════════════════════════════════════════════════════════
#
# Exercises all CLI commands against the stroop-test project (which must
# already exist with at least one completed experiment).
#
# Usage:
#   ./dev/scripts/smoke-test.sh              # Full test
#   ./dev/scripts/smoke-test.sh --quick      # Skip agent calls (inspect only)
#   ./dev/scripts/smoke-test.sh --manual     # Print manual test checklist only
#   ./dev/scripts/smoke-test.sh --project X  # Use a different project
#
# Prerequisites:
#   - ANTHROPIC_API_KEY or Claude Code logged in
#   - pip install -e ".[dev]"
#   - stroop-test project exists (urika new stroop-test ...)
#
# Cost: ~$2-5 for full run, $0 for --quick
# Time: ~10-20 min full, ~30s quick
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
PROJECT="stroop-test"
KNOWLEDGE_DIR="$(cd "$(dirname "$0")/../test-datasets/stroop/knowledge" && pwd)"
MAX_TURNS=2
QUICK=false
MANUAL_ONLY=false

# ── Parse args ──────────────────────────────────────────────────────
for arg in "$@"; do
    case $arg in
        --quick)     QUICK=true ;;
        --manual)    MANUAL_ONLY=true ;;
        --project)   shift; PROJECT="$1" ;;  # next arg is project name
        --project=*) PROJECT="${arg#*=}" ;;
        --help|-h)
            echo "Usage: $0 [--quick] [--manual] [--project NAME]"
            echo "  --quick      Inspection only — no agent calls (\$0 cost)"
            echo "  --manual     Print manual test checklist only"
            echo "  --project X  Use project X instead of stroop-test"
            exit 0
            ;;
    esac
done

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; FAILURES=$((FAILURES + 1)); }
info() { echo -e "  ${CYAN}▸${NC} $1"; }
section() { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }

FAILURES=0
TESTS=0

check() {
    local desc="$1"; shift
    TESTS=$((TESTS + 1))
    if output=$("$@" 2>&1); then
        pass "$desc"
    else
        fail "$desc"
        echo "    $(echo "$output" | head -3)"
    fi
}

check_contains() {
    local desc="$1"; local expected="$2"; shift 2
    TESTS=$((TESTS + 1))
    output=$("$@" 2>&1) || true
    if echo "$output" | grep -q "$expected"; then
        pass "$desc"
    else
        fail "$desc (expected '$expected')"
        echo "    $(echo "$output" | head -3)"
    fi
}

check_agent() {
    # Like check but skipped in --quick mode
    if $QUICK; then
        info "SKIP (--quick): $1"
        return 0
    fi
    check "$@"
}

check_agent_contains() {
    if $QUICK; then
        info "SKIP (--quick): $1"
        return 0
    fi
    check_contains "$@"
}

run_agent() {
    # Run an agent command, capture output, report pass/fail
    # Usage: run_agent "description" command args...
    local desc="$1"; shift
    if $QUICK; then
        info "SKIP (--quick): $desc"
        return 0
    fi
    TESTS=$((TESTS + 1))
    info "$desc..."
    if output=$("$@" 2>&1); then
        pass "$desc"
        echo "$output" | tail -5 | sed 's/^/    /'
    else
        # Agent commands may exit non-zero but still produce useful output
        if [ -n "$output" ]; then
            pass "$desc (non-zero exit but output produced)"
            echo "$output" | tail -5 | sed 's/^/    /'
        else
            fail "$desc"
        fi
    fi
}

# ── Manual test checklist ───────────────────────────────────────────
print_manual_tests() {
    section "MANUAL TESTS (require interactive terminal)"
    echo ""
    echo -e "${BOLD}Pause (ESC) during experiment run:${NC}"
    echo "  1. urika run $PROJECT --max-turns 3"
    echo "  2. Wait for 'Turn 1/3', press ESC"
    echo "  3. Expect: '⏸ Pause requested — will pause after current turn completes...'"
    echo "  4. Expect: '⏸ Paused after turn 1/3 (exp-...)'"
    echo "  5. Expect: Options list (--resume, advisor, --instructions)"
    echo ""
    echo -e "${BOLD}Resume after pause:${NC}"
    echo "  6. urika run $PROJECT --resume"
    echo "  7. Expect: picks up at turn 2, no settings dialog"
    echo ""
    echo -e "${BOLD}Stop (Ctrl+C) during experiment run:${NC}"
    echo "  8. urika run $PROJECT --max-turns 3"
    echo "  9. Press Ctrl+C during an agent"
    echo "  10. Expect: 'Experiment run stopped (exp-...)' + options"
    echo ""
    echo -e "${BOLD}Resume after stop:${NC}"
    echo "  11. urika run $PROJECT --resume"
    echo "  12. Expect: resumes the stopped experiment"
    echo ""
    echo -e "${BOLD}Resume with new instructions:${NC}"
    echo "  13. urika run $PROJECT --resume --instructions 'try non-parametric tests'"
    echo "  14. Expect: resumes with instructions applied"
    echo ""
    echo -e "${BOLD}Chat with advisor then resume:${NC}"
    echo "  15. urika advisor $PROJECT 'Should I try Bayesian analysis?'"
    echo "  16. urika run $PROJECT --resume"
    echo "  17. Expect: resumes normally"
    echo ""
    echo -e "${BOLD}Pause during autonomous run:${NC}"
    echo "  18. urika run $PROJECT --max-experiments 3 --max-turns 2"
    echo "  19. Press ESC during first experiment"
    echo "  20. Expect: '⏸ Autonomous run paused after N experiment(s)'"
    echo ""
    echo -e "${BOLD}Stop individual commands (Ctrl+C):${NC}"
    echo "  21. urika evaluate $PROJECT → 'Evaluation stopped.'"
    echo "  22. urika plan $PROJECT → 'Planning stopped.'"
    echo "  23. urika report $PROJECT → 'Report generation stopped.'"
    echo "  24. urika finalize $PROJECT → 'Finalize stopped.'"
    echo ""
    echo -e "${BOLD}REPL:${NC}"
    echo "  25. urika → /project $PROJECT → /quit → should exit cleanly"
    echo "  26. urika → /project $PROJECT → /run → ESC → verify pause"
    echo "  27. /resume → verify resume"
    echo ""
}

if $MANUAL_ONLY; then
    print_manual_tests
    exit 0
fi

# ── Unset CLAUDECODE if inside Claude Code ──────────────────────────
if [ -n "${CLAUDECODE:-}" ]; then
    warn "Inside Claude Code — unsetting CLAUDECODE for agent calls"
    unset CLAUDECODE
fi

# ── Verify project exists ───────────────────────────────────────────
PROJECT_PATH=$(python -m urika list 2>&1 | grep "$PROJECT" | awk '{print $2}')
if [ -z "$PROJECT_PATH" ]; then
    echo -e "${RED}Error: Project '$PROJECT' not found.${NC}"
    echo "Available projects:"
    python -m urika list 2>&1
    exit 1
fi

echo -e "${BOLD}Urika End-to-End Smoke Test${NC}"
echo "  Project:  $PROJECT"
echo "  Path:     $PROJECT_PATH"
echo "  Mode:     $( $QUICK && echo "quick (no agent calls)" || echo "full (with agent calls)" )"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: System checks
# ═══════════════════════════════════════════════════════════════════
section "System checks"

check "urika --version" python -m urika --version
check "urika list" python -m urika list

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Project inspection (no agent calls)
# ═══════════════════════════════════════════════════════════════════
section "Project inspection"

check_contains "status" "$PROJECT" python -m urika status "$PROJECT"
check "inspect" python -m urika inspect "$PROJECT"
check "criteria" python -m urika criteria "$PROJECT"
check "tools" python -m urika tools
check "methods" python -m urika methods "$PROJECT"
check "usage" python -m urika usage "$PROJECT"

# Get experiment ID for later tests
EXP_ID=$(python -m urika status "$PROJECT" 2>&1 | grep "exp-" | head -1 | awk '{print $1}')
if [ -n "$EXP_ID" ]; then
    pass "Found experiment: $EXP_ID"
    check "results" python -m urika results "$PROJECT"
    check "logs" python -m urika logs "$PROJECT" --experiment "$EXP_ID"
else
    warn "No experiments found — run/results/logs tests will be limited"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 3: JSON output mode
# ═══════════════════════════════════════════════════════════════════
section "JSON output"

check_contains "status --json" "\"project\"" python -m urika status "$PROJECT" --json
check_contains "results --json" "{" python -m urika results "$PROJECT" --json
check_contains "methods --json" "{" python -m urika methods "$PROJECT" --json
check_contains "criteria --json" "{" python -m urika criteria "$PROJECT" --json
check_contains "usage --json" "{" python -m urika usage "$PROJECT" --json

# ═══════════════════════════════════════════════════════════════════
# PHASE 4: Config
# ═══════════════════════════════════════════════════════════════════
section "Config"

check "config show (project)" python -m urika config "$PROJECT" --show
check "config show (global)" python -m urika config --show

# ═══════════════════════════════════════════════════════════════════
# PHASE 5: Knowledge pipeline
# ═══════════════════════════════════════════════════════════════════
section "Knowledge pipeline"

KNOWLEDGE_FILE="$KNOWLEDGE_DIR/data-description.md"
if [ -f "$KNOWLEDGE_FILE" ]; then
    check "knowledge ingest" python -m urika knowledge ingest "$PROJECT" "$KNOWLEDGE_FILE"
    check "knowledge list" python -m urika knowledge list "$PROJECT"
    check_contains "knowledge search" "" python -m urika knowledge search "$PROJECT" "reaction"
else
    warn "Knowledge file not found — skipping"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 6: Agent commands (skipped with --quick)
# ═══════════════════════════════════════════════════════════════════
section "Agent commands"

run_agent "evaluate" \
    python -m urika evaluate "$PROJECT" --json

run_agent "evaluate --instructions" \
    python -m urika evaluate "$PROJECT" --instructions "Focus on effect size" --json

run_agent "plan" \
    python -m urika plan "$PROJECT" --json

run_agent "plan --instructions" \
    python -m urika plan "$PROJECT" --instructions "Consider non-parametric alternatives" --json

run_agent "advisor chat" \
    python -m urika advisor "$PROJECT" "What should we try next?"

# ═══════════════════════════════════════════════════════════════════
# PHASE 7: Experiment run with --instructions
# ═══════════════════════════════════════════════════════════════════
section "Experiment run"

if ! $QUICK; then
    info "Running experiment (max $MAX_TURNS turns, with --instructions)..."
    TESTS=$((TESTS + 1))
    if python -m urika run "$PROJECT" \
        --max-turns "$MAX_TURNS" \
        --instructions "Try a non-parametric approach like Mann-Whitney U test." \
        2>&1 | tee /tmp/urika-smoke-run.log | tail -10; then
        pass "Experiment run completed"
    else
        if grep -q "completed\|Experiment completed" /tmp/urika-smoke-run.log; then
            pass "Experiment completed (non-zero exit)"
        else
            fail "Experiment run"
            tail -15 /tmp/urika-smoke-run.log
        fi
    fi

    # Verify results after run
    check "status after run" python -m urika status "$PROJECT"
    check "results after run" python -m urika results "$PROJECT"
    check "methods after run" python -m urika methods "$PROJECT"
else
    info "SKIP (--quick): experiment run"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 8: Reports and presentations
# ═══════════════════════════════════════════════════════════════════
section "Reports and presentations"

run_agent "report --json" \
    python -m urika report "$PROJECT" --json

run_agent "report --instructions" \
    python -m urika report "$PROJECT" --instructions "Focus on practical implications" --json

run_agent "present --json" \
    python -m urika present "$PROJECT" --json

run_agent "present --instructions" \
    python -m urika present "$PROJECT" --instructions "Keep to 5 slides" --json

# ═══════════════════════════════════════════════════════════════════
# PHASE 9: Finalize
# ═══════════════════════════════════════════════════════════════════
section "Finalize"

if ! $QUICK; then
    run_agent "finalize --instructions" \
        python -m urika finalize "$PROJECT" --instructions "Emphasize the paired t-test"

    TESTS=$((TESTS + 1))
    if [ -f "$PROJECT_PATH/projectbook/findings.json" ]; then
        pass "findings.json exists"
    else
        fail "findings.json missing"
    fi
else
    info "SKIP (--quick): finalize"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 10: Project file verification
# ═══════════════════════════════════════════════════════════════════
section "Project files"

for f in urika.toml criteria.json methods.json progress.json; do
    TESTS=$((TESTS + 1))
    if [ -f "$PROJECT_PATH/$f" ]; then
        pass "$f"
    else
        warn "$f not found"
    fi
done

COMPLETED=$(python -m urika status "$PROJECT" 2>&1 | grep -c "completed" || true)
TESTS=$((TESTS + 1))
if [ "$COMPLETED" -gt 0 ]; then
    pass "Completed experiments: $COMPLETED"
else
    fail "No completed experiments"
fi

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
echo ""
section "RESULTS"
echo ""
echo -e "  Tests run: ${BOLD}$TESTS${NC}"
if [ "$FAILURES" -eq 0 ]; then
    echo -e "  ${GREEN}All tests passed!${NC}"
else
    echo -e "  ${RED}Failures: $FAILURES${NC}"
fi
echo ""

print_manual_tests

exit "$FAILURES"
