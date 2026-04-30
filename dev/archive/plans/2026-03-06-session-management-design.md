# Session Management Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 7 of Urika — experiment orchestration for start/pause/resume/complete lifecycle.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Experiment orchestration only | Track active experiment, manage lifecycle, checkpoint for resumption. No cross-experiment comparison. |
| Storage | JSON files only | Consistent with rest of codebase. `session.json` per experiment. Debuggable. |
| Interface | Pure functions | Functions operating on project_dir + experiment_id. Matches progress.py pattern. |
| Locking | Simple lockfile | Empty `.lock` file in experiment dir. Sufficient for single-machine use. |
| Module location | `src/urika/core/session.py` | Single module in core/, alongside experiment.py and progress.py. |

---

## 2. State Model

A `session.json` file inside each experiment directory tracks orchestration state:

```python
@dataclass
class SessionState:
    """Orchestration state for an active experiment."""
    experiment_id: str
    status: str                           # "running" | "paused" | "completed" | "failed"
    started_at: str                       # ISO timestamp
    paused_at: str | None = None          # When last paused
    completed_at: str | None = None       # When completed/failed
    current_turn: int = 0                 # Orchestrator turn counter
    max_turns: int | None = None          # Turn limit (None = unlimited)
    agent_sessions: dict[str, str] = {}   # role -> SDK session_id for resumption
    checkpoint: dict[str, Any] = {}       # Arbitrary checkpoint data for orchestrator
```

- `agent_sessions` maps agent roles (e.g. `"task_agent"`, `"evaluator"`) to their Claude SDK `session_id`, enabling conversation resumption on `urika run --continue`.
- `checkpoint` holds orchestrator-specific state (e.g. which suggestion was last acted on, what stage of the loop).
- `status` tracks the runtime state (running/paused/completed/failed), distinct from `ExperimentConfig.status` which tracks the scientific outcome.

Stored at: `experiments/{experiment_id}/session.json`

---

## 3. Functions

### Lifecycle

```python
def start_session(project_dir: Path, experiment_id: str,
                  max_turns: int | None = None) -> SessionState:
    """Start orchestration for an experiment. Creates session.json and lockfile."""

def pause_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Pause a running session. Updates status, removes lockfile."""

def resume_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Resume a paused session. Restores status to running, re-acquires lock."""

def complete_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Mark session as completed. Updates status, removes lockfile."""

def fail_session(project_dir: Path, experiment_id: str,
                 error: str | None = None) -> SessionState:
    """Mark session as failed. Records error in checkpoint, removes lockfile."""
```

### State Management

```python
def load_session(project_dir: Path, experiment_id: str) -> SessionState | None:
    """Load session state, or None if no session.json exists."""

def save_session(project_dir: Path, experiment_id: str,
                 state: SessionState) -> None:
    """Persist session state to session.json."""

def update_turn(project_dir: Path, experiment_id: str) -> SessionState:
    """Increment turn counter. Returns updated state."""

def record_agent_session(project_dir: Path, experiment_id: str,
                         role: str, session_id: str) -> None:
    """Store an agent's SDK session_id for later resumption."""
```

### Locking

```python
def acquire_lock(project_dir: Path, experiment_id: str) -> bool:
    """Create .lock file. Returns False if already locked."""

def release_lock(project_dir: Path, experiment_id: str) -> None:
    """Remove .lock file."""

def is_locked(project_dir: Path, experiment_id: str) -> bool:
    """Check if experiment is locked."""
```

### Query

```python
def get_active_experiment(project_dir: Path) -> str | None:
    """Find which experiment is currently running. Scans for lockfiles."""
```

---

## 4. Lockfile

A simple empty file at `experiments/{experiment_id}/.lock`.

- Created by `start_session()` and `resume_session()`.
- Removed by `pause_session()`, `complete_session()`, and `fail_session()`.
- No PID tracking — just presence/absence.
- `acquire_lock()` returns `False` if `.lock` already exists.

---

## 5. Integration Points

- **`urika run`** calls `start_session()` or `resume_session()` depending on `--continue` flag.
- **Orchestrator** calls `update_turn()` each loop iteration, checks if `current_turn >= max_turns`.
- **Orchestrator** calls `record_agent_session()` after each agent run to store SDK session IDs.
- **`urika run --continue`** calls `load_session()` to get `agent_sessions` dict for conversation resumption.
- **Ctrl+C / interruption** calls `pause_session()` via signal handler in the CLI layer.
- **`urika status`** calls `get_active_experiment()` and `load_session()` to show current state.

---

## 6. What This Module Does NOT Do

- No orchestrator loop logic (separate future module).
- No agent dispatching.
- No experiment creation (that's `experiment.py`).
- No progress tracking (that's `progress.py`).

This module is purely the state machine for experiment orchestration — start, pause, resume, complete, fail — plus plumbing to track agent sessions and turns.
