"""Experiment orchestration: start, pause, resume, complete."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from urika.core.models import SessionState


def _session_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / "session.json"


def _lock_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / ".lock"


def load_session(project_dir: Path, experiment_id: str) -> SessionState | None:
    """Load session state, or None if no session.json exists."""
    path = _session_path(project_dir, experiment_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return SessionState.from_dict(data)


def save_session(project_dir: Path, experiment_id: str, state: SessionState) -> None:
    """Persist session state to session.json."""
    path = _session_path(project_dir, experiment_id)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n")


def acquire_lock(project_dir: Path, experiment_id: str) -> bool:
    """Create .lock file. Returns False if already locked."""
    path = _lock_path(project_dir, experiment_id)
    if path.exists():
        return False
    path.touch()
    return True


def release_lock(project_dir: Path, experiment_id: str) -> None:
    """Remove .lock file."""
    path = _lock_path(project_dir, experiment_id)
    if path.exists():
        path.unlink()


def is_locked(project_dir: Path, experiment_id: str) -> bool:
    """Check if experiment is locked."""
    return _lock_path(project_dir, experiment_id).exists()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_session(
    project_dir: Path,
    experiment_id: str,
    max_turns: int | None = None,
) -> SessionState:
    """Start orchestration for an experiment. Creates session.json and lockfile."""
    if not acquire_lock(project_dir, experiment_id):
        msg = f"Experiment {experiment_id} is already running"
        raise RuntimeError(msg)

    state = SessionState(
        experiment_id=experiment_id,
        status="running",
        started_at=_now_iso(),
        max_turns=max_turns,
    )
    save_session(project_dir, experiment_id, state)
    return state


def pause_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Pause a running session. Updates status, removes lockfile."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "paused"
    state.paused_at = _now_iso()
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    return state


def resume_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Resume a paused or failed session. Restores status to running, re-acquires lock."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    if state.status not in ("paused", "failed"):
        msg = f"Cannot resume experiment {experiment_id}: status is '{state.status}'"
        raise RuntimeError(msg)

    if not acquire_lock(project_dir, experiment_id):
        msg = f"Experiment {experiment_id} is already running"
        raise RuntimeError(msg)

    state.status = "running"
    save_session(project_dir, experiment_id, state)
    return state


def complete_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Mark session as completed. Updates status, removes lockfile."""
    from urika.core.progress import update_experiment_status

    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "completed"
    state.completed_at = _now_iso()
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    try:
        update_experiment_status(project_dir, experiment_id, "completed")
    except Exception:
        pass  # progress.json may not exist yet
    return state


def fail_session(
    project_dir: Path, experiment_id: str, error: str | None = None
) -> SessionState:
    """Mark session as failed. Records error in checkpoint, removes lockfile."""
    from urika.core.progress import update_experiment_status

    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "failed"
    state.completed_at = _now_iso()
    if error is not None:
        state.checkpoint["error"] = error
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    try:
        update_experiment_status(project_dir, experiment_id, "failed")
    except Exception:
        pass  # progress.json may not exist yet
    return state


def update_turn(project_dir: Path, experiment_id: str) -> SessionState:
    """Increment turn counter. Returns updated state."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.current_turn += 1
    save_session(project_dir, experiment_id, state)
    return state


def record_agent_session(
    project_dir: Path, experiment_id: str, role: str, session_id: str
) -> None:
    """Store an agent's SDK session_id for later resumption."""
    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.agent_sessions[role] = session_id
    save_session(project_dir, experiment_id, state)


def get_active_experiment(project_dir: Path) -> str | None:
    """Find which experiment is currently running. Scans for lockfiles."""
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.exists():
        return None

    for exp_dir in sorted(experiments_dir.iterdir()):
        if exp_dir.is_dir() and (exp_dir / ".lock").exists():
            return exp_dir.name
    return None
