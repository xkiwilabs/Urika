# CLI Wiring Design

**Date**: 2026-03-09
**Status**: Approved
**Context**: Phase 9 of Urika — wire existing infrastructure into CLI commands.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | 4 new commands/groups | Essential commands before agents are wired up. |
| Module changes | `cli.py` only | Pure wiring — no new core modules needed. |
| `experiment` | Click group with `create` and `list` subcommands | Mirrors the project hierarchy. |
| `results` | Standalone command | Shows leaderboard + optional per-experiment view. |
| `methods` / `tools` | Standalone commands with `--category` filter | Lists available built-in + project-specific methods/tools. |
| Helper | `_resolve_project(name)` | Extracts repeated registry lookup + error handling. |

---

## 2. New Commands

### `urika experiment create <project> <name> --hypothesis "..."`

- Resolves project via registry
- Calls `create_experiment(project_dir, name, hypothesis)`
- Prints the new experiment ID

### `urika experiment list <project>`

- Resolves project via registry
- Calls `list_experiments(project_dir)`
- Shows: experiment ID, name, status, run count (via `load_progress`)

### `urika results <project> [--experiment EXP_ID]`

- Without `--experiment`: loads `leaderboard.json` via `load_leaderboard()`, displays ranked methods
- With `--experiment`: loads `progress.json` for that experiment, shows runs sorted by primary metric

### `urika methods [--category CAT] [--project NAME]`

- Without `--project`: discovers only built-in methods via `MethodRegistry.discover()`
- With `--project`: also calls `discover_project()` on the project's `methods/` directory
- `--category`: filters by category
- Output: name, category, description (one line per method)

### `urika tools [--category CAT] [--project NAME]`

- Same pattern as `methods` but using `ToolRegistry`

---

## 3. Shared Helper

```python
def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name, return (project_dir, config). Raises ClickException on error."""
```

Replaces the repeated pattern in `status` and used by all project-scoped commands.

---

## 4. Imports Added

- `create_experiment` from `urika.core.experiment`
- `load_leaderboard` from `urika.evaluation.leaderboard`
- `MethodRegistry` from `urika.methods`
- `ToolRegistry` from `urika.tools`

---

## 5. What This Does NOT Do

- No `urika run` (needs orchestrator/agents)
- No `urika knowledge` commands (needs knowledge pipeline)
- No `urika report` / `urika labbook` (future phase)
- No changes to any core modules
