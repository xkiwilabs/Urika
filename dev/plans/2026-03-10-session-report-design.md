# Session Management & Report Generation Design

**Date**: 2026-03-10
**Status**: Approved
**Context**: Wire existing session and labbook infrastructure into CLI and orchestrator.

---

## 1. Session Management (`urika run --continue`)

### Orchestrator

Modify `run_experiment()` to accept `resume=False` parameter:
- When `resume=False` (default): existing behavior — calls `start_session`
- When `resume=True`: calls `resume_session`, loads last suggestion from `progress.json` as initial task prompt, starts loop from `current_turn`

### CLI

Add `--continue` flag to `urika run`:
- When set: loads session, verifies it's paused/failed, calls `run_experiment(..., resume=True)`
- When not set: existing behavior (start fresh)

### Existing infrastructure used

- `session.py`: `start_session`, `pause_session`, `resume_session`, `update_turn`, locking
- `progress.py`: `load_progress` for last suggestion/run context
- `models.py`: `SessionState` with `current_turn`, `max_turns`, `status`

---

## 2. Report Generation (`urika report`)

### CLI

`urika report <project> [--experiment EXP_ID]`:
- Without `--experiment`: calls `generate_results_summary()` and `generate_key_findings()`, prints paths
- With `--experiment`: calls `generate_experiment_summary()` for that experiment, prints path
- Both refresh labbook notes via `update_experiment_notes()`

### Existing infrastructure used

- `labbook.py`: `generate_experiment_summary`, `generate_results_summary`, `generate_key_findings`, `update_experiment_notes`

---

## 3. File Changes

| Action | File | What |
|--------|------|------|
| Modify | `src/urika/orchestrator/loop.py` | Add `resume` param to `run_experiment` |
| Modify | `src/urika/cli.py` | Add `--continue` flag to `run`, add `report` command |
| Modify | `tests/test_orchestrator/test_loop.py` | Tests for resume behavior |
| Modify | `tests/test_cli.py` | Tests for `--continue` and `report` |

No new files, no new dependencies. Pure wiring.
