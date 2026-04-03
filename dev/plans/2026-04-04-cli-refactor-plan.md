# CLI & REPL Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split `cli.py` (5363 lines) into a `cli/` package and `repl_commands.py` (1669 lines) into a `repl/` package, organized by command group.

**Architecture:** Convert single files to packages with `__init__.py` re-exporting everything for backward compatibility. Move one command group at a time, running the full test suite after each move. All imports in external code continue to work unchanged via re-exports.

**Tech Stack:** Python packages, Click command groups, lazy imports for circular dependency avoidance.

---

## Critical constraints

1. **All 1127 tests must pass after every task** — no exceptions
2. **Entry point `urika = "urika.cli:cli"` must work unchanged**
3. **All `from urika.cli import X` statements must work unchanged** via `__init__.py` re-exports
4. **All `from urika.repl_commands import X` statements must work unchanged** via backward-compat shim
5. **Dev branch only — do NOT push to main or public**

## Dependency summary

External imports from `urika.cli`: `cli` (Click group), `_make_on_message`, `_sanitize_project_name`, `_offer_to_run_advisor_suggestions`, and 11 command functions imported dynamically by repl_commands.

External imports from `urika.repl_commands`: `GLOBAL_COMMANDS`, `PROJECT_COMMANDS`, `cmd_*` functions, `get_all_commands`, `get_command_names`, `get_project_names`, `get_experiment_ids`, `_user_input_callback`, `_get_repl_bus`, `_prompt_numbered`, `get_global_stats`.

---

### Task 1: Create cli/ package with __init__.py and _helpers.py

**Files:**
- Create: `src/urika/cli/__init__.py`
- Create: `src/urika/cli/_helpers.py`
- Keep: `src/urika/cli.py` temporarily renamed to `src/urika/cli/_legacy.py`

**Step 1:** Create the package directory
```bash
mkdir -p src/urika/cli
```

**Step 2:** Move `cli.py` to `cli/_legacy.py`
```bash
git mv src/urika/cli.py src/urika/cli/_legacy.py
```

**Step 3:** Create `cli/__init__.py` that re-exports everything from `_legacy.py`
```python
"""Urika CLI — Click command group and all commands."""
from urika.cli._legacy import *  # noqa: F401,F403
from urika.cli._legacy import (
    cli,
    _make_on_message,
    _sanitize_project_name,
    _offer_to_run_advisor_suggestions,
    # All command functions that repl_commands imports dynamically
    new,
    list_cmd,
    status,
    run,
    report,
    inspect,
    logs,
    finalize,
    config_command,
    notifications_command,
    update_project,
    present,
    dashboard,
)
```

**Step 4:** Run full test suite
```bash
cd /home/mrichardson/Projects/Urika && python -m pytest -x -q 2>&1 | tail -10
```
Expected: ALL 1127 PASS — nothing should break since all imports resolve to the same code.

**Step 5:** Verify entry point still works
```bash
python -m urika --help
```

**Step 6:** Commit
```bash
git add -A && git commit -m "refactor: convert cli.py to cli/ package — no behavior change"
```

---

### Task 2: Extract shared helpers to cli/_helpers.py

**Files:**
- Modify: `src/urika/cli/_legacy.py` — remove helper functions
- Create: `src/urika/cli/_helpers.py` — receive helper functions
- Modify: `src/urika/cli/__init__.py` — re-export helpers

**Step 1:** Move these functions from `_legacy.py` to `_helpers.py`:
- `_make_on_message()` (line 22)
- `_record_agent_usage()` (line 47)
- `_sanitize_project_name()` (line 77)
- `_projects_dir()` (line 99)
- `_resolve_project()` (line 107)
- `_ensure_project()` (line 120)
- `_test_endpoint()` (line 186)
- `_prompt_numbered()` (line 206)
- `_prompt_path()` (line 219)

In `_helpers.py`, add all necessary imports these functions need (click, Path, os, re, etc.).

In `_legacy.py`, replace the removed functions with imports:
```python
from urika.cli._helpers import (
    _make_on_message,
    _record_agent_usage,
    _sanitize_project_name,
    _projects_dir,
    _resolve_project,
    _ensure_project,
    _test_endpoint,
    _prompt_numbered,
    _prompt_path,
)
```

Update `__init__.py` to also re-export from `_helpers`:
```python
from urika.cli._helpers import _make_on_message, _sanitize_project_name
```

**Step 2:** Run full test suite
```bash
python -m pytest -x -q
```

**Step 3:** Commit
```bash
git add -A && git commit -m "refactor: extract shared CLI helpers to cli/_helpers.py"
```

---

### Task 3: Extract project commands to cli/project.py

**Files:**
- Create: `src/urika/cli/project.py`
- Modify: `src/urika/cli/_legacy.py` — remove project commands

**Step 1:** Move these commands from `_legacy.py` to `project.py`:
- `new()` command and all its helpers (`_run_builder_agent_loop`, `_ingest_knowledge`)
- `list_cmd()` command
- `status()` command
- `update_project()` command
- `inspect()` command

In `project.py`, import the `cli` Click group from `_legacy` and the helpers from `_helpers`:
```python
from urika.cli._legacy import cli
from urika.cli._helpers import _resolve_project, _ensure_project, _sanitize_project_name, ...
```

Register commands with `@cli.command()` as before.

In `_legacy.py`, remove the moved functions and add:
```python
import urika.cli.project  # noqa: F401 — registers commands
```

Update `__init__.py` to import `project` module:
```python
import urika.cli.project  # noqa: F401
from urika.cli.project import new, status, list_cmd, update_project, inspect
```

**Step 2:** Run full test suite

**Step 3:** Commit
```bash
git commit -m "refactor: extract project commands to cli/project.py"
```

---

### Task 4: Extract run command to cli/run.py

**Files:**
- Create: `src/urika/cli/run.py`
- Modify: `src/urika/cli/_legacy.py`

**Step 1:** Move the `run()` command and its helpers:
- `run()` command (~800 lines)
- `_determine_next_experiment()` helper
- `_offer_to_run_advisor_suggestions()` helper

This is the biggest single command. It needs imports for: signal, time, asyncio, click, Path, plus urika internals (orchestrator, agents, cli_display, notifications, session).

In `run.py`:
```python
from urika.cli._legacy import cli
from urika.cli._helpers import _resolve_project, _ensure_project, _record_agent_usage, _make_on_message, ...
```

Update `__init__.py`:
```python
import urika.cli.run  # noqa: F401
from urika.cli.run import run, _determine_next_experiment, _offer_to_run_advisor_suggestions
```

**Step 2:** Run full test suite

**Step 3:** Commit
```bash
git commit -m "refactor: extract run command to cli/run.py"
```

---

### Task 5: Extract agent commands to cli/agents.py

**Files:**
- Create: `src/urika/cli/agents.py`
- Modify: `src/urika/cli/_legacy.py`

**Step 1:** Move these commands:
- `advisor()` command
- `evaluate()` command
- `plan()` command
- `report()` command and `_run_report_agent()` helper
- `present()` command
- `finalize()` command
- `build_tool()` command
- `criteria()` command

Update `__init__.py` with re-exports.

**Step 2:** Run full test suite

**Step 3:** Commit
```bash
git commit -m "refactor: extract agent commands to cli/agents.py"
```

---

### Task 6: Extract config commands to cli/config.py

**Files:**
- Create: `src/urika/cli/config.py`
- Modify: `src/urika/cli/_legacy.py`

**Step 1:** Move these commands:
- `config_command()` and all `_config_*` helpers
- `notifications_command()` and all `_notifications_*`, `_show_notification_config`, `_send_test_notification`, `_save_notification_settings` helpers
- `setup_command()` and all setup helpers
- `dashboard()` command

Update `__init__.py` with re-exports.

**Step 2:** Run full test suite

**Step 3:** Commit
```bash
git commit -m "refactor: extract config commands to cli/config.py"
```

---

### Task 7: Extract remaining commands to cli/data.py

**Files:**
- Create: `src/urika/cli/data.py`
- Modify: `src/urika/cli/_legacy.py`

**Step 1:** Move remaining commands:
- `results()` command
- `methods()` command
- `tools()` command
- `logs()` command
- `usage()` command
- `knowledge` subgroup (if it exists as a Click group)

After this, `_legacy.py` should contain ONLY:
- The `cli` Click group definition
- The `invoke_without_command` handler (REPL launcher)
- Imports of all submodules to register commands

**Step 2:** Run full test suite

**Step 3:** Commit
```bash
git commit -m "refactor: extract data/results commands to cli/data.py"
```

---

### Task 8: Clean up _legacy.py → move remaining to __init__.py

**Files:**
- Modify: `src/urika/cli/__init__.py` — absorb remaining _legacy.py content
- Delete: `src/urika/cli/_legacy.py`

**Step 1:** Move the `cli` Click group definition and the REPL launcher from `_legacy.py` into `__init__.py`. Update all submodule imports to reference `cli` from `__init__`.

**Step 2:** Update all internal imports that reference `_legacy`:
```python
# In project.py, run.py, agents.py, config.py, data.py:
# Change: from urika.cli._legacy import cli
# To:     from urika.cli import cli
```

**Step 3:** Delete `_legacy.py`

**Step 4:** Run full test suite

**Step 5:** Commit
```bash
git commit -m "refactor: remove _legacy.py — cli/ package complete"
```

---

### Task 9: Create repl/ package

**Files:**
- Create: `src/urika/repl/__init__.py`
- Rename: `src/urika/repl.py` → `src/urika/repl/main.py`
- Rename: `src/urika/repl_session.py` → `src/urika/repl/session.py`
- Rename: `src/urika/repl_commands.py` → `src/urika/repl/_all_commands.py`
- Create: `src/urika/repl_commands.py` — thin backward-compat shim
- Create: `src/urika/repl_session.py` — thin backward-compat shim

**Step 1:** Create the package:
```bash
mkdir -p src/urika/repl
```

Note: `src/urika/repl.py` already exists as a file. To convert to a package, we need to:
1. Move `repl.py` → `repl_main.py` temporarily
2. Create `repl/` directory
3. Move `repl_main.py` → `repl/main.py`

**Step 2:** Create `repl/__init__.py`:
```python
"""Urika interactive REPL."""
from urika.repl.main import start_repl

__all__ = ["start_repl"]
```

**Step 3:** Create backward-compat shims at the old paths:
```python
# src/urika/repl_commands.py (shim)
"""Backward-compat shim — imports from urika.repl package."""
from urika.repl._all_commands import *  # noqa: F401,F403
from urika.repl._all_commands import (
    GLOBAL_COMMANDS, PROJECT_COMMANDS,
    _user_input_callback, _repl_session_ref, _get_repl_bus,
    _prompt_numbered, _dashboard_server,
    get_all_commands, get_command_names, get_project_names, get_experiment_ids,
    get_global_stats,
    # All cmd_ functions...
)
```

```python
# src/urika/repl_session.py (shim)
"""Backward-compat shim."""
from urika.repl.session import *  # noqa: F401,F403
from urika.repl.session import ReplSession
```

**Step 4:** Run full test suite

**Step 5:** Commit
```bash
git commit -m "refactor: convert repl.py and repl_commands.py to repl/ package"
```

---

### Task 10: Split repl commands into focused files

**Files:**
- Create: `src/urika/repl/commands.py` — simple commands (help, list, project, quit, etc.)
- Create: `src/urika/repl/cmd_run.py` — cmd_run, cmd_resume, _parse_remote_run_args
- Create: `src/urika/repl/cmd_agents.py` — cmd_advisor through cmd_build_tool
- Create: `src/urika/repl/helpers.py` — _pick_experiment, _run_single_agent, _save_presentation, etc.
- Modify: `src/urika/repl/_all_commands.py` — slim down to just imports and registration

Follow the same pattern as the CLI split:
1. Move one group at a time
2. Keep `_all_commands.py` as the import hub initially
3. Run tests after each move

**Step 1:** Extract helpers to `helpers.py`

**Step 2:** Extract simple commands to `commands.py`

**Step 3:** Extract `cmd_run` to `cmd_run.py`

**Step 4:** Extract agent commands to `cmd_agents.py`

**Step 5:** Slim down `_all_commands.py` to just imports and re-exports

**Step 6:** Run full test suite

**Step 7:** Commit
```bash
git commit -m "refactor: split repl commands into focused files"
```

---

### Task 11: Clean up backward-compat shims

**Step 1:** Check if any external code still imports from the old paths (`urika.repl_commands`, `urika.repl_session`). If only internal code does, update those imports to use the new paths and remove the shims.

**Step 2:** Update `__init__.py` files to export only what's needed.

**Step 3:** Run full test suite

**Step 4:** Commit
```bash
git commit -m "refactor: update internal imports to new package paths"
```

---

### Task 12: Final verification

**Step 1:** Run full test suite
```bash
python -m pytest -v 2>&1 | tail -30
```

**Step 2:** Verify CLI entry point
```bash
python -m urika --help
python -m urika list --json
python -m urika status dht-target-selection-v2
```

**Step 3:** Verify REPL launches
```bash
echo "/help" | timeout 5 python -m urika 2>&1 | head -20
```

**Step 4:** Check no file is over 1500 lines
```bash
find src/urika -name "*.py" -exec wc -l {} \; | sort -rn | head -10
```

**Step 5:** Final commit
```bash
git commit -m "refactor: cli.py and repl_commands.py split complete — all tests passing"
```

---

## Task dependency order

```
Task 1 (create package)
  → Task 2 (extract helpers)
  → Task 3 (project commands)
  → Task 4 (run command)
  → Task 5 (agent commands)
  → Task 6 (config commands)
  → Task 7 (data commands)
  → Task 8 (remove _legacy.py)
  → Task 9 (create repl package)
  → Task 10 (split repl commands)
  → Task 11 (clean shims)
  → Task 12 (final verification)
```

Strictly sequential — each task depends on the previous. No parallelization possible.
