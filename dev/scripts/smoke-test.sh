#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Urika End-to-End Smoke Test
# ═══════════════════════════════════════════════════════════════════════
#
# Comprehensive functional test that exercises all CLI commands against
# a real project with real agent calls. Uses the stroop dataset (tiny,
# fast) for quick turnaround.
#
# Usage:
#   ./dev/scripts/smoke-test.sh              # Full test (creates project, runs everything)
#   ./dev/scripts/smoke-test.sh --skip-new   # Skip project creation (reuse existing)
#   ./dev/scripts/smoke-test.sh --quick      # Minimal run (1 turn, skip finalize)
#   ./dev/scripts/smoke-test.sh --manual     # Print manual test checklist only
#
# Prerequisites:
#   - ANTHROPIC_API_KEY or Claude Code logged in
#   - pip install -e ".[dev]"
#   - Stroop dataset: python dev/test-datasets/download.py --dataset stroop
#
# Cost: ~$2-5 depending on model and number of turns
# Time: ~10-30 minutes depending on agent speed
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
PROJECT="smoke-test-$$"  # Unique per run
DATA_DIR="$(cd "$(dirname "$0")/../test-datasets/stroop/data" && pwd)"
KNOWLEDGE_DIR="$(cd "$(dirname "$0")/../test-datasets/stroop/knowledge" && pwd)"
QUESTION="Is there a significant Stroop interference effect on reaction time?"
MODE="confirmatory"
DESCRIPTION="Stroop reaction time data. Within-subjects design, congruent vs incongruent conditions. ~130 trials across participants. Expect significant RT difference (p<0.05) with medium-large effect size (d>0.5). Use paired t-test as primary analysis, check normality assumptions."
MAX_TURNS=2
SKIP_NEW=false
QUICK=false
MANUAL_ONLY=false

# ── Parse args ──────────────────────────────────────────────────────
for arg in "$@"; do
    case $arg in
        --skip-new)  SKIP_NEW=true ;;
        --quick)     QUICK=true; MAX_TURNS=1 ;;
        --manual)    MANUAL_ONLY=true ;;
        --help|-h)
            echo "Usage: $0 [--skip-new] [--quick] [--manual]"
            echo "  --skip-new   Reuse existing smoke-test project"
            echo "  --quick      Minimal run (1 turn, skip finalize)"
            echo "  --manual     Print manual test checklist only"
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
    # Usage: check "description" command args...
    local desc="$1"
    shift
    TESTS=$((TESTS + 1))
    if output=$("$@" 2>&1); then
        pass "$desc"
        return 0
    else
        fail "$desc"
        echo "    Output: $(echo "$output" | head -3)"
        return 1
    fi
}

check_contains() {
    # Usage: check_contains "description" "expected_substring" command args...
    local desc="$1"
    local expected="$2"
    shift 2
    TESTS=$((TESTS + 1))
    if output=$("$@" 2>&1) && echo "$output" | grep -q "$expected"; then
        pass "$desc"
        return 0
    elif echo "$output" | grep -q "$expected"; then
        pass "$desc (non-zero exit but output matches)"
        return 0
    else
        fail "$desc (expected '$expected')"
        echo "    Output: $(echo "$output" | head -3)"
        return 1
    fi
}

# ── Manual test checklist ───────────────────────────────────────────
print_manual_tests() {
    section "MANUAL TESTS (require interactive terminal)"
    echo ""
    echo -e "${BOLD}Pause (ESC) during experiment run:${NC}"
    echo "  1. Run: urika run $PROJECT --max-turns 3"
    echo "  2. Wait for 'Turn 1/3' to appear"
    echo "  3. Press ESC"
    echo "  4. Verify: '⏸ Pause requested — will pause after current turn completes...'"
    echo "  5. Wait for turn to complete"
    echo "  6. Verify: '⏸ Paused after turn 1/3 (exp-...)'"
    echo "  7. Verify: Options list shown (--resume, advisor, --instructions)"
    echo ""
    echo -e "${BOLD}Resume after pause:${NC}"
    echo "  8. Run: urika run $PROJECT --resume"
    echo "  9. Verify: Picks up at turn 2, no settings dialog"
    echo ""
    echo -e "${BOLD}Stop (Ctrl+C) during experiment run:${NC}"
    echo "  10. Run: urika run $PROJECT --max-turns 3"
    echo "  11. Press Ctrl+C during an agent"
    echo "  12. Verify: 'Experiment run stopped (exp-...)'"
    echo "  13. Verify: Options list shown"
    echo ""
    echo -e "${BOLD}Resume after stop:${NC}"
    echo "  14. Run: urika run $PROJECT --resume"
    echo "  15. Verify: Resumes the stopped experiment"
    echo ""
    echo -e "${BOLD}Resume with new instructions:${NC}"
    echo "  16. Run: urika run $PROJECT --resume --instructions 'try non-parametric tests'"
    echo "  17. Verify: Resumes with instructions applied"
    echo ""
    echo -e "${BOLD}Chat with advisor then resume:${NC}"
    echo "  18. Run: urika advisor $PROJECT 'Should I try Bayesian analysis?'"
    echo "  19. Run: urika run $PROJECT --resume"
    echo "  20. Verify: Resumes normally"
    echo ""
    echo -e "${BOLD}Pause during autonomous run:${NC}"
    echo "  21. Run: urika run $PROJECT --max-experiments 3 --max-turns 2"
    echo "  22. Press ESC during first experiment"
    echo "  23. Verify: '⏸ Autonomous run paused after N experiment(s)'"
    echo ""
    echo -e "${BOLD}Stop individual commands:${NC}"
    echo "  24. Run: urika evaluate $PROJECT — press Ctrl+C → 'Evaluation stopped.'"
    echo "  25. Run: urika plan $PROJECT — press Ctrl+C → 'Planning stopped.'"
    echo "  26. Run: urika report $PROJECT — press Ctrl+C → 'Report generation stopped.'"
    echo "  27. Run: urika finalize $PROJECT — press Ctrl+C → 'Finalize stopped.'"
    echo ""
    echo -e "${BOLD}REPL tests:${NC}"
    echo "  28. Run: urika"
    echo "  29. Type: /project $PROJECT"
    echo "  30. Type: /quit → should exit (not say 'Cancelled')"
    echo "  31. Re-enter REPL, load project, type: /run"
    echo "  32. Press ESC → verify pause works in REPL"
    echo "  33. Type: /resume → verify resume works"
    echo ""
}

if $MANUAL_ONLY; then
    print_manual_tests
    exit 0
fi

# ── Unset CLAUDECODE if running inside Claude Code ──────────────────
if [ -n "${CLAUDECODE:-}" ]; then
    warn "Inside Claude Code session — unsetting CLAUDECODE for agent calls"
    unset CLAUDECODE
fi

echo -e "${BOLD}Urika End-to-End Smoke Test${NC}"
echo "  Project: $PROJECT"
echo "  Dataset: stroop ($DATA_DIR)"
echo "  Max turns: $MAX_TURNS"
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: System checks
# ═══════════════════════════════════════════════════════════════════
section "System checks"

check "urika --version" python -m urika --version
check "urika list" python -m urika list
check_contains "pytest passes" "passed" python -m pytest tests/ -x -q --tb=no

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Project creation
# ═══════════════════════════════════════════════════════════════════
section "Project creation"

if $SKIP_NEW; then
    info "Skipping project creation (--skip-new)"
    # Find existing smoke-test project
    PROJECT=$(python -m urika list 2>&1 | grep smoke-test | head -1 | awk '{print $1}')
    if [ -z "$PROJECT" ]; then
        fail "No existing smoke-test project found"
        exit 1
    fi
    pass "Using existing project: $PROJECT"
else
    # Create project non-interactively
    info "Creating project '$PROJECT' with stroop data..."
    if python -m urika new "$PROJECT" \
        --data "$DATA_DIR" \
        --question "$QUESTION" \
        --mode "$MODE" \
        --description "$DESCRIPTION" 2>&1 | tail -5; then
        pass "Project created"
    else
        fail "Project creation failed"
        exit 1
    fi
fi

PROJECT_PATH=$(python -m urika list 2>&1 | grep "$PROJECT" | awk '{print $2}')
info "Project path: $PROJECT_PATH"

# ═══════════════════════════════════════════════════════════════════
# PHASE 3: Project inspection commands (no agents)
# ═══════════════════════════════════════════════════════════════════
section "Project inspection (no agent calls)"

check_contains "status shows project" "$PROJECT" python -m urika status "$PROJECT"
check_contains "status shows question" "Stroop" python -m urika status "$PROJECT"
check "inspect data" python -m urika inspect "$PROJECT"
check "criteria" python -m urika criteria "$PROJECT"
check "tools list" python -m urika tools
check_contains "methods (empty ok)" "" python -m urika methods "$PROJECT" || true
check_contains "usage" "" python -m urika usage "$PROJECT" || true

# ═══════════════════════════════════════════════════════════════════
# PHASE 4: Knowledge pipeline
# ═══════════════════════════════════════════════════════════════════
section "Knowledge pipeline"

KNOWLEDGE_FILE="$KNOWLEDGE_DIR/data-description.md"
if [ -f "$KNOWLEDGE_FILE" ]; then
    check "knowledge ingest" python -m urika knowledge ingest "$PROJECT" "$KNOWLEDGE_FILE"
    check "knowledge list" python -m urika knowledge list "$PROJECT"
    check_contains "knowledge search" "" python -m urika knowledge search "$PROJECT" "stroop"
else
    warn "No knowledge file found at $KNOWLEDGE_FILE — skipping"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 5: Run experiment (agent calls start here)
# ═══════════════════════════════════════════════════════════════════
section "Experiment run (max $MAX_TURNS turns)"

info "Running experiment with instructions..."
if python -m urika run "$PROJECT" \
    --max-turns "$MAX_TURNS" \
    --instructions "Use a paired t-test as the primary analysis. Check normality with Shapiro-Wilk." \
    2>&1 | tee /tmp/urika-smoke-run.log | tail -10; then
    pass "Experiment completed"
else
    # Non-zero exit could be normal (e.g., max turns reached)
    if grep -q "completed\|Experiment completed" /tmp/urika-smoke-run.log; then
        pass "Experiment completed (non-zero exit)"
    else
        fail "Experiment run failed"
        tail -20 /tmp/urika-smoke-run.log
    fi
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 6: Results inspection
# ═══════════════════════════════════════════════════════════════════
section "Results inspection"

check "status after run" python -m urika status "$PROJECT"
check "results" python -m urika results "$PROJECT"
check "methods" python -m urika methods "$PROJECT"

# Get the experiment ID
EXP_ID=$(python -m urika status "$PROJECT" 2>&1 | grep "exp-" | head -1 | awk '{print $1}')
if [ -n "$EXP_ID" ]; then
    pass "Experiment found: $EXP_ID"
    check "logs" python -m urika logs "$PROJECT" --experiment "$EXP_ID"
else
    warn "No experiment ID found — skipping experiment-specific tests"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 7: Individual agent commands
# ═══════════════════════════════════════════════════════════════════
section "Individual agent commands"

info "Running evaluate..."
if python -m urika evaluate "$PROJECT" --json 2>&1 | head -5; then
    pass "evaluate"
else
    fail "evaluate"
fi

info "Running evaluate with --instructions..."
if python -m urika evaluate "$PROJECT" --instructions "Focus on effect size interpretation" --json 2>&1 | head -5; then
    pass "evaluate --instructions"
else
    fail "evaluate --instructions"
fi

info "Running plan..."
if python -m urika plan "$PROJECT" --json 2>&1 | head -5; then
    pass "plan"
else
    fail "plan"
fi

info "Running plan with --instructions..."
if python -m urika plan "$PROJECT" --instructions "Consider non-parametric alternatives" --json 2>&1 | head -5; then
    pass "plan --instructions"
else
    fail "plan --instructions"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 8: Advisor chat
# ═══════════════════════════════════════════════════════════════════
section "Advisor chat"

info "Chatting with advisor..."
if python -m urika advisor "$PROJECT" "What have we learned so far and what should we try next?" 2>&1 | tail -10; then
    pass "advisor chat"
else
    fail "advisor chat"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 9: Second run (tests advisor-suggested experiment)
# ═══════════════════════════════════════════════════════════════════
section "Second experiment run"

info "Running second experiment (advisor-driven)..."
if python -m urika run "$PROJECT" \
    --max-turns 1 \
    --instructions "Try a different statistical approach than the first experiment." \
    2>&1 | tee /tmp/urika-smoke-run2.log | tail -10; then
    pass "Second experiment completed"
else
    if grep -q "completed\|Experiment completed" /tmp/urika-smoke-run2.log; then
        pass "Second experiment completed (non-zero exit)"
    else
        fail "Second experiment failed"
    fi
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 10: Reports and presentations
# ═══════════════════════════════════════════════════════════════════
section "Reports and presentations"

if ! $QUICK; then
    info "Generating report..."
    if python -m urika report "$PROJECT" --json 2>&1 | head -5; then
        pass "report"
    else
        fail "report"
    fi

    info "Generating report with --instructions..."
    if python -m urika report "$PROJECT" --instructions "Focus on practical implications" --json 2>&1 | head -5; then
        pass "report --instructions"
    else
        fail "report --instructions"
    fi

    info "Generating presentation..."
    if python -m urika present "$PROJECT" --json 2>&1 | head -5; then
        pass "present"
    else
        fail "present"
    fi

    info "Generating presentation with --instructions..."
    if python -m urika present "$PROJECT" --instructions "Keep it to 5 slides" --json 2>&1 | head -5; then
        pass "present --instructions"
    else
        fail "present --instructions"
    fi
else
    info "Skipping reports/presentations (--quick mode)"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 11: Finalize
# ═══════════════════════════════════════════════════════════════════
section "Finalize"

if ! $QUICK; then
    info "Finalizing project..."
    if python -m urika finalize "$PROJECT" --instructions "Emphasize the paired t-test results" 2>&1 | tail -10; then
        pass "finalize --instructions"
    else
        fail "finalize"
    fi

    # Check finalize artifacts
    if [ -f "$PROJECT_PATH/projectbook/findings.json" ]; then
        pass "findings.json exists"
    else
        fail "findings.json missing"
    fi
else
    info "Skipping finalize (--quick mode)"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 12: JSON output mode
# ═══════════════════════════════════════════════════════════════════
section "JSON output mode"

check_contains "status --json" "\"project\"" python -m urika status "$PROJECT" --json
check_contains "results --json" "{" python -m urika results "$PROJECT" --json
check_contains "methods --json" "{" python -m urika methods "$PROJECT" --json
check_contains "criteria --json" "{" python -m urika criteria "$PROJECT" --json
check_contains "usage --json" "{" python -m urika usage "$PROJECT" --json

# ═══════════════════════════════════════════════════════════════════
# PHASE 13: Config
# ═══════════════════════════════════════════════════════════════════
section "Config"

check "config show (project)" python -m urika config "$PROJECT" --show
check "config show (global)" python -m urika config --show

# ═══════════════════════════════════════════════════════════════════
# PHASE 14: Session state checks
# ═══════════════════════════════════════════════════════════════════
section "Session state verification"

# Check that experiments have proper status
COMPLETED=$(python -m urika status "$PROJECT" 2>&1 | grep -c "completed" || true)
info "Completed experiments: $COMPLETED"
if [ "$COMPLETED" -gt 0 ]; then
    pass "At least one completed experiment"
else
    fail "No completed experiments found"
fi

# Check project files exist
for f in urika.toml criteria.json methods.json progress.json; do
    if [ -f "$PROJECT_PATH/$f" ]; then
        pass "$f exists"
    else
        warn "$f not found (may be expected)"
    fi
done

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

# Print manual test checklist
print_manual_tests

exit "$FAILURES"
