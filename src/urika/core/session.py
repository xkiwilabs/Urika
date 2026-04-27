"""Experiment orchestration: start, pause, resume, complete."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from urika.core.models import SessionState

logger = logging.getLogger(__name__)


def _session_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / "session.json"


def _lock_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / ".lock"


def load_session(project_dir: Path, experiment_id: str) -> SessionState | None:
    """Load session state, or None if no session.json exists."""
    path = _session_path(project_dir, experiment_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt JSON in %s: %s", path, exc)
        return None
    return SessionState.from_dict(data)


def save_session(project_dir: Path, experiment_id: str, state: SessionState) -> None:
    """Persist session state to session.json."""
    path = _session_path(project_dir, experiment_id)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


def acquire_lock(project_dir: Path, experiment_id: str) -> bool:
    """Acquire an experiment lock. Returns False if already locked (by a live process).

    A lock that already contains *our* own PID is treated as already
    acquired and returns True. This handles the dashboard handoff: the
    spawn helper pre-writes the lock with the subprocess's PID before
    `urika run` boots up, and when the subprocess then calls
    ``acquire_lock`` it would otherwise see its own PID, conclude the
    "other process" is alive, and refuse to acquire its own lock.
    """
    path = _lock_path(project_dir, experiment_id)
    if path.exists():
        # Check if the lock is stale (owning process is dead)
        try:
            pid_str = path.read_text().strip()
            if pid_str:
                pid = int(pid_str)
                if pid == os.getpid():
                    # Same process (e.g. dashboard wrote the lock with
                    # our PID before we started). Already ours — done.
                    return True
                os.kill(pid, 0)  # Check if process is alive (doesn't actually kill)
                return False  # Process is alive — lock is valid
            else:
                # Empty lock file (legacy) — check age
                import time

                age = time.time() - path.stat().st_mtime
                if age < 6 * 3600:  # Less than 6 hours old
                    return False
                # Older than 6 hours with no PID — assume stale
        except (ValueError, ProcessLookupError):
            # PID is dead or invalid — lock is stale, clean it up
            pass
        except PermissionError:
            return False  # Process exists but we can't signal it
        except OSError:
            return False  # Other OS error — be conservative
        # If we get here, the lock is stale — remove it
        try:
            path.unlink()
        except OSError:
            return False
    # Create new lock with our PID
    try:
        path.write_text(str(os.getpid()))
    except OSError:
        return False
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
    if not acquire_lock(project_dir, experiment_id):
        msg = f"Experiment {experiment_id} is already running (locked)"
        raise RuntimeError(msg)

    try:
        state = load_session(project_dir, experiment_id)
        if state is None:
            msg = f"No session found for experiment {experiment_id}"
            raise FileNotFoundError(msg)

        if state.status not in ("paused", "stopped", "failed"):
            msg = (
                f"Cannot resume experiment {experiment_id}: status is '{state.status}'"
            )
            raise RuntimeError(msg)

        state.status = "running"
        save_session(project_dir, experiment_id, state)
        return state
    except:
        release_lock(project_dir, experiment_id)
        raise


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
    except Exception as exc:
        logger.warning("Progress status update failed for completed session: %s", exc)
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
    except Exception as exc:
        logger.warning("Progress status update failed for failed session: %s", exc)
    return state


def stop_session(
    project_dir: Path, experiment_id: str, reason: str | None = None
) -> SessionState:
    """Mark session as stopped (deliberate user interruption). Removes lockfile."""
    from urika.core.progress import update_experiment_status

    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "stopped"
    state.completed_at = _now_iso()
    if reason is not None:
        state.checkpoint["reason"] = reason
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    try:
        update_experiment_status(project_dir, experiment_id, "stopped")
    except Exception as exc:
        logger.warning("Progress status update failed for stopped session: %s", exc)
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
