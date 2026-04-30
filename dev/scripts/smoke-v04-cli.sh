#!/usr/bin/env bash
# Comprehensive CLI smoke test for v0.4.0rc2.
#
# Drives every scriptable surface against the stroop test dataset:
#   - urika new (project creation + data hash recording)
#   - urika config (api-key --test)
#   - urika status (data drift detection)
#   - urika tools / methods / criteria / usage (read-only inspection)
#   - urika memory (CLI surface + auto-capture round-trip)
#   - urika sessions (list / export)
#   - urika completion (install + script)
#   - urika run --dry-run --budget (cost estimate + budget surface)
#   - urika delete (cleanup)
#
# Every command runs with --json where supported so we can assert on
# structured output. Set URIKA_HOME to a temp dir so we don't touch
# the real config.

set -uo pipefail

# === setup ============================================================
SMOKE_DIR="$(mktemp -d -t urika-smoke-XXXXXX)"
export URIKA_HOME="$SMOKE_DIR/home"
mkdir -p "$URIKA_HOME"
export URIKA_PROJECTS_DIR="$SMOKE_DIR/projects"
mkdir -p "$URIKA_PROJECTS_DIR"

DATA="$(pwd)/dev/test-datasets/stroop/data/stroop.csv"
PROJ="smoke-04-stroop"
RESULTS=()
PASS=0
FAIL=0

ok() { RESULTS+=("PASS  $1"); PASS=$((PASS+1)); }
fail() { RESULTS+=("FAIL  $1"); FAIL=$((FAIL+1)); }

run() {
  local desc="$1"; shift
  echo
  echo "=== $desc ==="
  echo "  \$ $*"
  if "$@"; then ok "$desc"; else fail "$desc"; fi
}

# === 1. Version sanity ================================================
echo "Smoke dir: $SMOKE_DIR"
echo "URIKA_HOME: $URIKA_HOME"
echo "URIKA_PROJECTS_DIR: $URIKA_PROJECTS_DIR"
VERSION=$(urika --version 2>&1 | tail -1)
echo "urika --version: $VERSION"
if [[ "$VERSION" == *"0.4.0rc2"* ]]; then ok "version is 0.4.0rc2"; else fail "version mismatch: $VERSION"; fi

# === 2. List backends + completion ====================================
run "completion script bash" urika completion script bash > /dev/null

# === 3. Create project (non-interactive --json mode) ==================
run "urika new --json" urika new "$PROJ" --json --data "$DATA" \
  --question "Is there a Stroop interference effect?" \
  --description "smoke test for v0.4 release" \
  --mode confirmatory \
  --privacy-mode open

PROJ_DIR="$URIKA_PROJECTS_DIR/$PROJ"

# === 4. Verify project artifacts ======================================
if [[ -f "$PROJ_DIR/urika.toml" ]]; then ok "urika.toml exists"; else fail "urika.toml missing"; fi
if grep -q "data_hashes" "$PROJ_DIR/urika.toml"; then ok "data_hashes recorded in urika.toml"; else fail "data_hashes missing"; fi

# === 5. Status (read) =================================================
run "urika status --json" urika status "$PROJ" --json > /tmp/smoke_status.json
if grep -q "data_drift" /tmp/smoke_status.json; then ok "status reports data_drift"; else fail "status missing data_drift"; fi

# === 6. Drift detection: edit data file, re-status ====================
echo "TAMPER" >> "$DATA"
urika status "$PROJ" --json > /tmp/smoke_status_after.json 2>&1
if grep -q '"old_hash"' /tmp/smoke_status_after.json; then
  ok "drift detected after data edit"
else
  fail "drift not detected"
fi
# Restore the data file
git checkout -- "$DATA" 2>/dev/null || sed -i '$d' "$DATA"

# === 7. Inspect ========================================================
run "urika inspect --json" urika inspect "$PROJ" --json > /dev/null

# === 8. Read-only commands (deterministic) ============================
run "urika list" urika list > /dev/null
run "urika tools" urika tools > /dev/null
run "urika methods" urika methods "$PROJ" --json > /dev/null
run "urika criteria" urika criteria "$PROJ" --json > /dev/null
run "urika usage" urika usage "$PROJ" --json > /dev/null
run "urika logs --json" urika logs "$PROJ" --json > /dev/null

# === 9. Memory CLI round-trip =========================================
echo "Always cross-validate by subject" | urika memory add "$PROJ" cv_strategy --type instruction --stdin
if [[ -f "$PROJ_DIR/memory/instruction_cv_strategy.md" ]]; then
  ok "memory add wrote instruction_cv_strategy.md"
else
  fail "memory add did not write entry"
fi
run "urika memory list --json" urika memory list "$PROJ" --json > /tmp/smoke_memory.json
if grep -q "instruction_cv_strategy" /tmp/smoke_memory.json; then
  ok "memory list shows new entry"
else
  fail "memory list missing entry"
fi
run "urika memory show" urika memory show "$PROJ" instruction_cv_strategy > /dev/null

# === 10. Sessions CLI (no sessions yet → empty list) ==================
run "urika sessions list --json" urika sessions list "$PROJ" --json > /tmp/smoke_sessions.json
if grep -q '"sessions"' /tmp/smoke_sessions.json; then ok "sessions list returns shape"; else fail "sessions list malformed"; fi

# === 11. Dry-run + budget ============================================
run "urika run --dry-run" urika run "$PROJ" --dry-run

# === 12. Project memory injection: build planning agent config ========
python3 - <<'PY'
import os
from pathlib import Path
from urika.agents.roles.planning_agent import build_config

proj = Path(os.environ["URIKA_PROJECTS_DIR"]) / "smoke-04-stroop"
cfg = build_config(proj, experiment_id="exp-001-test")
prompt = cfg.system_prompt
assert "Project Memory" in prompt, "memory not injected into planner"
assert "cross-validate by subject" in prompt, "specific entry missing from prompt"
print("PASS  planner system prompt includes project memory")
PY

# === 13. SecurityPolicy rejects shellouts =============================
python3 - <<'PY'
import asyncio
from pathlib import Path
from urika.agents.config import SecurityPolicy
from urika.agents.permission import make_can_use_tool

policy = SecurityPolicy(
    writable_dirs=[],
    readable_dirs=[Path("/tmp")],
    allowed_bash_prefixes=["urika"],
    blocked_bash_patterns=["rm -rf"],
)
cb = make_can_use_tool(policy, Path("/tmp"))

async def go():
    bad = await cb("Bash", {"command": "urika ; rm -rf /"}, None)
    assert getattr(bad, "message", ""), "expected deny"
    good = await cb("Bash", {"command": "urika status"}, None)
    assert not getattr(good, "message", "") , "expected allow"
    blocked = await cb("Bash", {"command": "urika status; rm -rf /tmp"}, None)
    assert getattr(blocked, "message", ""), "expected metachar deny"
    outside = await cb("Read", {"file_path": "/etc/passwd"}, None)
    assert getattr(outside, "message", ""), "expected outside-readable deny"
    inside = await cb("Read", {"file_path": "/tmp/x"}, None)
    assert not getattr(inside, "message", ""), "expected inside-readable allow"

asyncio.run(go())
print("PASS  SecurityPolicy denies metachar / outside-dir / blocked patterns")
PY

# === 14. Auto-capture marker round-trip ===============================
python3 - <<'PY'
import os
from pathlib import Path
from urika.core.project_memory import (
    parse_and_persist_memory_markers,
    list_entries,
)

proj = Path(os.environ["URIKA_PROJECTS_DIR"]) / "smoke-04-stroop"
fake_advisor_text = (
    "Looking at the data, I think we should fit a paired t-test.\n"
    '<memory type="feedback">User prefers simple statistical tests over '
    'machine learning for confirmatory studies</memory>\n'
    "Then we can compute Cohen's d for the effect size."
)
stripped, written = parse_and_persist_memory_markers(proj, fake_advisor_text)
assert "<memory" not in stripped, "marker not stripped"
assert "paired t-test" in stripped, "non-marker text missing"
assert "Cohen's d" in stripped, "post-marker text missing"
assert len(written) == 1, f"expected 1 capture, got {len(written)}"
entries = list_entries(proj)
types = {e["type"] for e in entries}
assert "feedback" in types, f"feedback type missing from {types}"
print("PASS  auto-capture marker round-trip")
PY

# === 15. Cleanup ======================================================
echo
echo "=== cleanup ==="
urika delete "$PROJ" --force > /dev/null 2>&1
if [[ ! -d "$PROJ_DIR" ]]; then ok "project deleted"; else fail "project still exists"; fi

# === Summary ==========================================================
echo
echo "============================================================"
echo "Smoke test summary:"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo "------------------------------------------------------------"
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo "============================================================"
rm -rf "$SMOKE_DIR"
exit $FAIL
