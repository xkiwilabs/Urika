# Project Delete + Trash Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add a "trash project" operation across CLI / TUI / dashboard. Trashing unregisters a project and moves its directory to `~/.urika/trash/<name>-<timestamp>/`. Urika never `rm`'s; users empty trash manually.

**Architecture:** One core helper (`project_delete.py`) does the move + manifest + registry update. Every surface (CLI, TUI, dashboard) is a thin wrapper around it. Trashing a missing-folder project is automatic registry-only cleanup. Active-run lockfile blocks the operation.

**Tech Stack:** Python stdlib (`shutil.move`, `pathlib`), existing `ProjectRegistry`, FastAPI for the dashboard endpoint, click for the CLI.

**Out of scope (decided):** restore command, size warnings, bulk delete, trash quotas.

---

## Phase 1 — Core helper

### Task 1.1: `trash_project()` core helper + manifest

**Files:**
- Create: `src/urika/core/project_delete.py`
- Test: `tests/test_core/test_project_delete.py`

**Step 1: Write failing tests**

Cover:
- Trash a registered project with files → folder appears at `~/.urika/trash/<name>-<ts>/` containing the original tree + a `.urika-trash-manifest.json` at the root (with `original_path`, `registered_name`, `trashed_at`, `urika_version`).
- Registry entry removed from `~/.urika/projects.json`.
- Result has `registry_only=False`, `trash_path` set, `original_path` correct.
- Trash a project whose folder is already missing → `registry_only=True`, `trash_path=None`, registry entry removed, no exception.
- Active-run guard: `.lock` file anywhere under the project → raises `ActiveRunError` with the lock path in the message; registry untouched, folder untouched.
- Same-name re-delete: trash a project, recreate one with the same name, trash again → both end up in trash with distinct timestamped dirs (no collision).
- Unknown project name → raises `ProjectNotFoundError`.
- Deletion log: each successful call appends one JSON line to `~/.urika/deletion-log.jsonl` (name, original_path, trash_path or null, ts, registry_only flag).
- Cross-filesystem move: monkeypatch `shutil.move` to verify it's called (we trust shutil's same/cross-fs handling; we don't reimplement it).

Use `URIKA_HOME` env var to redirect both registry and trash root into `tmp_path`.

**Step 2: Run failing tests** — confirm `ImportError` / no module.

**Step 3: Implement `trash_project()`**

Module: `src/urika/core/project_delete.py`

```python
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from urika.core.registry import ProjectRegistry

MANIFEST_NAME = ".urika-trash-manifest.json"


class ProjectNotFoundError(Exception):
    """Project name is not in the registry."""


class ActiveRunError(Exception):
    """A .lock file under the project blocks deletion."""

    def __init__(self, lock_path: Path) -> None:
        super().__init__(f"Active run lock found at {lock_path}; stop the run first.")
        self.lock_path = lock_path


@dataclass
class TrashResult:
    name: str
    original_path: Path
    trash_path: Path | None
    registry_only: bool


def _urika_home() -> Path:
    env = os.environ.get("URIKA_HOME")
    return Path(env) if env else Path.home() / ".urika"


def _trash_root() -> Path:
    return _urika_home() / "trash"


def _deletion_log() -> Path:
    return _urika_home() / "deletion-log.jsonl"


def _find_active_lock(project_path: Path) -> Path | None:
    for lock in project_path.rglob("*.lock"):
        if lock.is_file():
            return lock
    return None


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _write_manifest(project_path: Path, name: str, original_path: Path) -> None:
    from urika import __version__

    manifest = {
        "registered_name": name,
        "original_path": str(original_path),
        "trashed_at": datetime.now(timezone.utc).isoformat(),
        "urika_version": __version__,
    }
    (project_path / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def _append_deletion_log(entry: dict) -> None:
    log = _deletion_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def trash_project(name: str) -> TrashResult:
    """Move a registered project to ~/.urika/trash/ and unregister it.

    If the project's folder is already missing, only the registry entry is
    removed (registry_only=True). Active .lock files under the project
    raise ActiveRunError without modifying anything.
    """
    registry = ProjectRegistry()
    original_path = registry.get(name)
    if original_path is None:
        raise ProjectNotFoundError(name)

    if not original_path.exists():
        registry.remove(name)
        _append_deletion_log(
            {
                "name": name,
                "original_path": str(original_path),
                "trash_path": None,
                "registry_only": True,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        return TrashResult(
            name=name,
            original_path=original_path,
            trash_path=None,
            registry_only=True,
        )

    lock = _find_active_lock(original_path)
    if lock is not None:
        raise ActiveRunError(lock)

    _write_manifest(original_path, name, original_path)

    trash_root = _trash_root()
    trash_root.mkdir(parents=True, exist_ok=True)
    trash_path = trash_root / f"{name}-{_timestamp()}"
    # Extremely unlikely to collide given second-precision timestamps,
    # but guard anyway in case two trashes land in the same second.
    counter = 1
    while trash_path.exists():
        trash_path = trash_root / f"{name}-{_timestamp()}-{counter}"
        counter += 1

    shutil.move(str(original_path), str(trash_path))
    registry.remove(name)

    _append_deletion_log(
        {
            "name": name,
            "original_path": str(original_path),
            "trash_path": str(trash_path),
            "registry_only": False,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )

    return TrashResult(
        name=name,
        original_path=original_path,
        trash_path=trash_path,
        registry_only=False,
    )
```

Check `ProjectRegistry` for an existing `remove()` method. If not present, add one in this task: it must operate atomically on `~/.urika/projects.json` (use existing `filelock` helper if registry already does — match the pattern).

**Step 4: Run tests, confirm green.**

**Step 5: Commit** — `feat(core): trash_project helper moves projects to ~/.urika/trash/`

---

## Phase 2 — CLI

### Task 2.1: `urika delete <name>` command

**Files:**
- Modify: `src/urika/cli/project.py` (or wherever `urika list` lives — same module)
- Test: `tests/test_cli_project.py` (add to existing or create)

**Step 1: Write failing tests**

Cover:
- `urika delete foo` with stdin `y\n` → trashes the project, prints "Moved 'foo' to <trash_path>".
- `urika delete foo` with stdin `n\n` → aborts, registry untouched.
- `urika delete foo --force` → no prompt, trashes immediately.
- `urika delete missing-name` → exit 1 with helpful error ("not registered").
- `urika delete foo` with active lock → exit 1, message includes the lock path.
- `urika delete foo` when folder already missing → trashes with no second prompt for the move (registry_only path), prints "Unregistered 'foo' (folder was already missing)".
- `--json` flag emits the `TrashResult` as JSON.

Use Click's `CliRunner` with `URIKA_HOME` redirected to `tmp_path`.

**Step 2: Run failing tests.**

**Step 3: Implement**

```python
@cli.command()
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON result.")
def delete(name: str, force: bool, json_output: bool) -> None:
    """Move a project to ~/.urika/trash/ and unregister it.

    The project directory is moved (not deleted) so artifacts are
    preserved. Empty the trash manually when you're sure.
    """
    from urika.core.project_delete import (
        ActiveRunError,
        ProjectNotFoundError,
        trash_project,
    )

    if not force:
        try:
            click.confirm(
                f"Move project '{name}' to ~/.urika/trash/? "
                "(files preserved, registry entry removed)",
                abort=True,
            )
        except click.Abort:
            click.echo("Aborted.")
            return

    try:
        result = trash_project(name)
    except ProjectNotFoundError:
        raise click.ClickException(f"Project '{name}' is not registered.")
    except ActiveRunError as e:
        raise click.ClickException(str(e))

    if json_output:
        from urika.cli_helpers import output_json
        output_json(
            {
                "name": result.name,
                "original_path": str(result.original_path),
                "trash_path": (
                    str(result.trash_path) if result.trash_path else None
                ),
                "registry_only": result.registry_only,
            }
        )
        return

    if result.registry_only:
        click.echo(
            f"Unregistered '{name}' "
            f"(folder at {result.original_path} was already missing)."
        )
    else:
        click.echo(f"Moved '{name}' to {result.trash_path}")
```

**Step 4: Run tests, confirm green.**

**Step 5: Commit** — `feat(cli): urika delete moves project to trash and unregisters`

### Task 2.2: `urika list --prune` flag

**Files:**
- Modify: `src/urika/cli/project.py` (the `list` command)
- Test: `tests/test_cli_project.py`

**Step 1: Write failing tests**

- `urika list --prune` with two registered projects, one missing → unregisters the missing one silently, prints "Pruned 1 stale entry: <name>" then the remaining list.
- `urika list --prune` with all paths valid → "No stale entries." then the list.

**Step 2-3: Add `--prune` option and walk registry; for each missing path call `trash_project()` (which falls into registry-only branch).**

**Step 4: Tests green.**

**Step 5: Commit** — `feat(cli): urika list --prune unregisters missing-folder entries`

---

## Phase 3 — TUI / REPL

### Task 3.1: `/delete <name>` slash command

**Files:**
- Modify: `src/urika/repl/commands.py`
- Test: `tests/test_tui/test_commands.py` (or appropriate)

**Step 1: Tests**

Mirror existing slash-command tests. Cover:
- `/delete <name>` triggers stdin confirm via the existing stdin bridge; `y` → trashes; `n` → aborts.
- `/delete <name>` for unknown name → friendly error message inline.

**Step 2-3: Implement** as a thin wrapper that calls `trash_project()` after the bridge confirm. Match the formatting of other slash commands. If the user is currently in the project that was just deleted, clear the project context and print a navigation hint.

**Step 4: Tests green.**

**Step 5: Commit** — `feat(repl): /delete <name> slash command moves project to trash`

---

## Phase 4 — Dashboard

### Task 4.1: `DELETE /api/projects/<name>` endpoint

**Files:**
- Modify: `src/urika/dashboard/routers/api.py`
- Test: `tests/test_dashboard/test_api_delete_project.py` (new)

**Step 1: Tests**

- DELETE on unknown project → 404
- DELETE on a project with `.lock` → 422, lock path in `detail`
- DELETE on registered project → 200, body has `trash_path`, registry entry removed
- DELETE on missing-folder project → 200, body has `registry_only: true`, `trash_path: null`
- HX-Request → response includes `HX-Redirect: /projects`

**Step 2-3: Implement**

```python
@router.delete("/projects/{name}")
async def api_delete_project(name: str, request: Request):
    from urika.core.project_delete import (
        ActiveRunError,
        ProjectNotFoundError,
        trash_project,
    )
    try:
        result = trash_project(name)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown project")
    except ActiveRunError as e:
        raise HTTPException(status_code=422, detail=str(e))

    payload = {
        "name": result.name,
        "trash_path": (
            str(result.trash_path) if result.trash_path else None
        ),
        "registry_only": result.registry_only,
    }
    if request.headers.get("hx-request") == "true":
        return Response(
            status_code=200,
            headers={"HX-Redirect": "/projects"},
        )
    return JSONResponse(payload)
```

**Step 4: Tests green.**

**Step 5: Commit** — `feat(dashboard): DELETE /api/projects/<name> trashes the project`

### Task 4.2: Danger zone in project settings + missing-card unregister button

**Files:**
- Modify: `src/urika/dashboard/templates/project_settings.html` (add a Danger zone section to the existing layout — does NOT need a new tab; can sit at the bottom of all tabs or as a new tab depending on existing structure)
- Modify: `src/urika/dashboard/templates/projects_list.html` (add inline "Unregister" link next to missing-tagged projects)
- Modify: `src/urika/dashboard/static/app.css` (small `.danger-zone` styling — red accent, not pink)
- Test: `tests/test_dashboard/test_pages_settings.py` and `test_pages_projects.py`

**Step 1: Tests**

- Project settings page renders a Danger zone heading + "Move to trash" button + the trash path it would use.
- Projects list page: a project marked `missing=True` shows an inline "Unregister" form/button posting DELETE to that project.
- Active-lock case: settings page shows a disabled button with "Stop the running [evaluate / finalize / run] first" message instead of the active button.

**Step 2-3: Implement**

Project-settings danger zone — typed-name confirmation:

```html
<section class="card danger-zone">
  <h2>Danger zone</h2>
  <p class="text-muted">
    Moving the project to trash unregisters it from Urika and moves
    the project folder to <code>~/.urika/trash/{{ project.name }}-&lt;timestamp&gt;/</code>.
    Files are preserved; you can delete the trash folder manually when
    you're sure.
  </p>
  <div x-data="{ typed: '' }">
    <input
      type="text"
      class="input"
      placeholder="Type the project name to confirm"
      x-model="typed"
    >
    <button
      class="btn btn--danger"
      :disabled="typed !== '{{ project.name }}'"
      hx-delete="/api/projects/{{ project.name }}"
      hx-confirm="Move {{ project.name }} to trash?"
    >Move to trash</button>
  </div>
</section>
```

Active-run guard server-side: in `project_settings` view, walk the project for any `.lock` files; if found, pass a flag down so the template renders disabled state instead.

Projects list — for each `missing` project, render a small inline form:

```html
{% if project.missing %}
  <button
    class="btn btn--ghost btn--small"
    hx-delete="/api/projects/{{ project.name }}"
    hx-confirm="Unregister '{{ project.name }}'? (folder is already missing)"
  >Unregister</button>
{% endif %}
```

CSS: add a `.btn--danger` token (red bg) and `.danger-zone` (red border + dim background). Reuse existing tokens — don't introduce new ones unless necessary.

**Step 4: Tests green.**

**Step 5: Commit** — `feat(dashboard): danger zone in project settings + unregister missing projects`

---

## Phase 5 — Docs + smoke

### Task 5.1: Update docs

**Files:**
- Modify: `docs/15-cli-reference.md` — add `urika delete` and `urika list --prune`
- Modify: `docs/19-dashboard.md` — add Danger zone section, mention DELETE endpoint in API table, and the missing-project unregister button on the projects list
- Modify: `docs/16-interactive-tui.md` — add `/delete` slash command

Single commit: `docs: project trash + delete across CLI/TUI/dashboard`

### Task 5.2: Smoke checklist

**Files:**
- Create: `dev/plans/2026-04-26-project-delete-smoke.md`

Manual checks:
- [ ] `urika delete foo` prompts, then moves to trash; trash dir contains manifest + tree
- [ ] `urika delete foo --force` skips prompt
- [ ] Re-delete same name after recreating → second trash dir has different timestamp
- [ ] Active run blocks trash with helpful message
- [ ] `urika list --prune` cleans missing entries
- [ ] `/delete` slash command works in TUI
- [ ] Dashboard danger zone: type-name-to-enable, click → redirects to projects list, project gone
- [ ] Missing project on `/projects` shows "Unregister" button → click → entry removed
- [ ] `~/.urika/deletion-log.jsonl` accumulates one line per operation

Commit: `docs(smoke): project delete + trash smoke checklist`

---

## Execution

Use **superpowers:subagent-driven-development**. Dispatch one subagent per task in order. Phase 1 must complete before any other phase starts (everything depends on the core helper). Phases 2 / 3 / 4 can each go in their own subagent batch sequentially. Phase 5 closes out.

**No `Co-Authored-By: Claude` lines in any commit.**

---

## Extension — experiment-level trash (2026-04-26)

Same trash semantics ported one level down. Lets users discard a bad/wrong experiment, clean up clutter before sharing, or recover from a crashed experiment that materialized but never wrote progress.

**Surfaces:**
- Core helper: `src/urika/core/experiment_delete.py` (`trash_experiment(project_path, project_name, exp_id)`)
- CLI: `urika experiment delete <project> <exp_id>` with `--force` and `--json`
- Dashboard API: `DELETE /api/projects/<n>/experiments/<exp_id>` (404 unknown project, 422 unknown experiment / active lock, HX-Redirect to `/projects/<n>/experiments` on HTMX)
- Dashboard UI: small ghost-style Delete button on every experiment row (not gated on status), and a Danger zone on the experiment detail page mirroring the project-settings type-name confirm

**Differences from the project-trash design:**
- Trash root is **project-local** (`<project>/trash/<exp_id>-<ts>/`), NOT `~/.urika/trash/`. Keeps related artifacts together, survives project rename/move, avoids cross-project name collisions.
- Reuses `_is_active_run_lock`, `_pid_is_alive`, `_urika_home`, `_find_active_lock`, `_timestamp`, `MANIFEST_NAME` from `urika.core.project_delete`. Only the result dataclass + the orchestration shape are duplicated.
- Manifest carries `kind: "experiment"`, `project_name`, `experiment_id` (vs. `registered_name` for projects). Deletion-log lines carry `kind: "experiment"` too so a single tail of `~/.urika/deletion-log.jsonl` can mix both.
- No registry mutation — experiments aren't in the central registry.
- No `registry_only` branch (an experiment dir either exists or doesn't; if it doesn't, that's a 422/ExperimentNotFoundError).

**Tests:** 22 new (8 core + 5 CLI + 6 API + 3 page render). Full suite goes from 2171 → 2193.
