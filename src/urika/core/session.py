"""Experiment orchestration: start, pause, resume, complete."""

from __future__ import annotations

import json
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


def save_session(
    project_dir: Path, experiment_id: str, state: SessionState
) -> None:
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
