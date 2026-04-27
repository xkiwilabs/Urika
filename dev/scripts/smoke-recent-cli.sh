#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# Recent CLI Work — Scriptable Smoke Test
# ═══════════════════════════════════════════════════════════════════════
#
# Exercises every CLI / TUI surface added or changed in the 2026-04-26 →
# 2026-04-27 work. NO API keys required, NO agent calls — these tests
# verify command wiring, flag parsing, registry operations, and trash
# semantics. Each test runs in ~1 second.
#
# Pair this with the manual checklist at
# dev/2026-04-27-tester-checklist.md for the dashboard / agent flows
# that DO need API keys + a browser.
#
# Usage:
#   ./dev/scripts/smoke-recent-cli.sh
#
# Cost: $0
# Time: ~10 seconds
# Requires: pip install -e ".[dev]"
#
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

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

check_not_contains() {
    local desc="$1"; local unexpected="$2"; shift 2
    TESTS=$((TESTS + 1))
    output=$("$@" 2>&1) || true
    if echo "$output" | grep -q "$unexpected"; then
        fail "$desc (unexpected '$unexpected')"
    else
        pass "$desc"
    fi
}

check_succeeds() {
    local desc="$1"; shift
    TESTS=$((TESTS + 1))
    if "$@" >/dev/null 2>&1; then
        pass "$desc"
    else
        fail "$desc (command failed)"
    fi
}

check_fails() {
    local desc="$1"; shift
    TESTS=$((TESTS + 1))
    if ! "$@" >/dev/null 2>&1; then
        pass "$desc"
    else
        fail "$desc (command unexpectedly succeeded)"
    fi
}

# ── Sandbox ──────────────────────────────────────────────────────────
# Use an isolated URIKA_HOME so we don't pollute the real registry
# or mistakenly trash production projects.

SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT

export URIKA_HOME="$SANDBOX/.urika"
export URIKA_PROJECTS_DIR="$SANDBOX/projects"
mkdir -p "$URIKA_HOME" "$URIKA_PROJECTS_DIR"

echo -e "${BOLD}Recent CLI Work — Smoke Test${NC}"
echo "  Sandbox:  $SANDBOX"
echo "  No agent calls, no API keys needed."
echo ""

# ═══════════════════════════════════════════════════════════════════
# PHASE 1: --help output for new flags + commands
# ═══════════════════════════════════════════════════════════════════
section "Help output — new commands & flags"

check_contains "urika --help lists 'delete'" "delete" \
    python -m urika --help

check_contains "urika delete --help mentions trash" "trash" \
    python -m urika delete --help

check_contains "urika delete --help has --force" "\-\-force" \
    python -m urika delete --help

check_contains "urika delete --help has --json" "\-\-json" \
    python -m urika delete --help

check_contains "urika list --help has --prune" "\-\-prune" \
    python -m urika list --help

check_contains "urika experiment --help lists 'delete'" "delete" \
    python -m urika experiment --help

check_contains "urika run --help has --advisor-first" "\-\-advisor-first" \
    python -m urika run --help

check_contains "urika summarize --help has --instructions" "\-\-instructions" \
    python -m urika summarize --help

# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Project create + delete (trash) cycle
# ═══════════════════════════════════════════════════════════════════
section "Project trash cycle"

# Create a throwaway project (non-interactively via env-driven defaults
# and piped input — but since `urika new` is heavily interactive, we
# materialise the project files by hand and register them).

PROJ_NAME="smoke-test-proj"
PROJ_DIR="$URIKA_PROJECTS_DIR/$PROJ_NAME"
mkdir -p "$PROJ_DIR/experiments/exp-001"
cat > "$PROJ_DIR/urika.toml" <<TOML
[project]
name = "$PROJ_NAME"
question = "Smoke-test research question"
mode = "exploratory"
description = ""

[preferences]
audience = "standard"
TOML
cat > "$PROJ_DIR/experiments/exp-001/experiment.json" <<JSON
{"experiment_id": "exp-001", "name": "smoke", "hypothesis": "h",
 "status": "completed", "created_at": "2026-04-27T00:00:00Z"}
JSON
echo "{\"$PROJ_NAME\": \"$PROJ_DIR\"}" > "$URIKA_HOME/projects.json"

check_contains "urika list shows the project" "$PROJ_NAME" \
    python -m urika list

check_contains "urika delete --force --json" "trash_path" \
    python -m urika delete "$PROJ_NAME" --force --json

# After delete, the project should be unregistered.
check_not_contains "urika list no longer shows the project" "$PROJ_NAME" \
    python -m urika list

# Trash dir should exist with the project files.
TESTS=$((TESTS + 1))
if ls "$URIKA_HOME/trash/" 2>/dev/null | grep -q "$PROJ_NAME"; then
    pass "Trash dir contains the project"
else
    fail "Trash dir missing the project"
fi

# ═══════════════════════════════════════════════════════════════════
# PHASE 3: list --prune
# ═══════════════════════════════════════════════════════════════════
section "list --prune"

# Register a project pointing at a non-existent path.
echo "{\"ghost-proj\": \"$URIKA_PROJECTS_DIR/nonexistent\"}" > "$URIKA_HOME/projects.json"

check_contains "list --prune unregisters missing folders" "Pruned" \
    python -m urika list --prune

# After --prune, registry should be empty.
check_not_contains "ghost-proj is gone after prune" "ghost-proj" \
    python -m urika list

# ═══════════════════════════════════════════════════════════════════
# PHASE 4: Unknown / active-lock guards
# ═══════════════════════════════════════════════════════════════════
section "Trash safety guards"

# Re-create a project for the guard tests
mkdir -p "$PROJ_DIR/experiments/exp-001"
cat > "$PROJ_DIR/urika.toml" <<TOML
[project]
name = "$PROJ_NAME"
question = "q"
mode = "exploratory"
description = ""

[preferences]
audience = "standard"
TOML
cat > "$PROJ_DIR/experiments/exp-001/experiment.json" <<JSON
{"experiment_id": "exp-001", "name": "smoke", "hypothesis": "h",
 "status": "completed", "created_at": "2026-04-27T00:00:00Z"}
JSON
echo "{\"$PROJ_NAME\": \"$PROJ_DIR\"}" > "$URIKA_HOME/projects.json"

check_fails "urika delete unknown-name fails" \
    python -m urika delete "definitely-not-a-real-project" --force

# Drop a live PID lock under the project — our own PID is alive.
echo "$$" > "$PROJ_DIR/experiments/exp-001/.lock"

check_contains "urika delete blocked by active lock" "lock" \
    python -m urika delete "$PROJ_NAME" --force

# Clean up the lock so the project can be deleted in subsequent tests
rm -f "$PROJ_DIR/experiments/exp-001/.lock"

# ═══════════════════════════════════════════════════════════════════
# PHASE 5: Experiment delete CLI
# ═══════════════════════════════════════════════════════════════════
section "Experiment delete (urika experiment delete)"

# Make sure exp-001 exists
mkdir -p "$PROJ_DIR/experiments/exp-001"
cat > "$PROJ_DIR/experiments/exp-001/experiment.json" <<JSON
{"experiment_id": "exp-001", "name": "smoke", "hypothesis": "h",
 "status": "completed", "created_at": "2026-04-27T00:00:00Z"}
JSON

check_contains "urika experiment delete --force" "Moved" \
    python -m urika experiment delete "$PROJ_NAME" "exp-001" --force

# Project-local trash dir should now contain exp-001.
TESTS=$((TESTS + 1))
if ls "$PROJ_DIR/trash/" 2>/dev/null | grep -q "exp-001"; then
    pass "Project-local trash contains exp-001"
else
    fail "Project-local trash missing exp-001"
fi

# Unknown experiment → fails
check_fails "urika experiment delete unknown experiment fails" \
    python -m urika experiment delete "$PROJ_NAME" "exp-bogus" --force

# ═══════════════════════════════════════════════════════════════════
# PHASE 6: TUI / REPL slash command registration
# ═══════════════════════════════════════════════════════════════════
section "TUI / REPL slash commands present"

# Each of the recently-added slash commands should be importable and
# registered. We import the module and check the command name appears
# in the registry.

check_succeeds "import /delete handler" \
    python -c "from urika.repl_commands import cmd_delete; assert callable(cmd_delete)"

check_succeeds "import /delete-experiment handler" \
    python -c "from urika.repl_commands import cmd_delete_experiment; assert callable(cmd_delete_experiment)"

check_succeeds "/delete in command registry" \
    python -c "from urika.repl_commands import GLOBAL_COMMANDS; assert 'delete' in GLOBAL_COMMANDS"

check_succeeds "/delete-experiment in project registry" \
    python -c "from urika.repl_commands import PROJECT_COMMANDS; assert 'delete-experiment' in PROJECT_COMMANDS"

# ═══════════════════════════════════════════════════════════════════
# PHASE 7: Pytest sweep (optional — skip if pytest unavailable)
# ═══════════════════════════════════════════════════════════════════
section "Test suite (optional)"

if command -v pytest >/dev/null 2>&1; then
    info "Running pytest -q (this takes ~60s)..."
    TESTS=$((TESTS + 1))
    if pytest -q >/tmp/urika-pytest-out.log 2>&1; then
        TOTAL=$(tail -5 /tmp/urika-pytest-out.log | grep -oE "[0-9]+ passed" | head -1)
        pass "pytest: $TOTAL"
    else
        fail "pytest had failures"
        tail -10 /tmp/urika-pytest-out.log
    fi
else
    warn "pytest not available — skipping"
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
    echo ""
    echo "Next: walk through dev/2026-04-27-tester-checklist.md for the"
    echo "dashboard / agent / TUI flows that need a browser + API keys."
else
    echo -e "  ${RED}Failures: $FAILURES${NC}"
fi
echo ""

exit "$FAILURES"
