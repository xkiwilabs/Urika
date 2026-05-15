"""Experiment orchestration: start, pause, resume, complete."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from urika.core.atomic_write import write_json_atomic
from urika.core.models import SessionState

logger = logging.getLogger(__name__)


def _session_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / "session.json"


def _lock_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / ".lock"


def _pid_is_alive(pid: int) -> bool:
    """Return True iff a process with this PID is currently alive.

    Cross-platform via psutil. Pre-this-fix the lockfile logic used
    ``os.kill(pid, 0)`` and only treated ``ProcessLookupError`` as
    "dead PID" — but on Windows ``os.kill(dead_pid, 0)`` raises
    ``OSError(WinError 87)``, not ``ProcessLookupError``. The catch-all
    ``except OSError: return False`` (where False meant "lock is valid")
    therefore concluded EVERY dead PID was alive on Windows, leaving
    locks effectively permanent. Reported by a Windows beta tester
    whose project became unusable after the first failed run.

    psutil.pid_exists handles the platform-specific WinError codes
    (87 = invalid PID, 5 = access-denied = process exists, 6 = invalid
    handle, etc.) and returns the right answer everywhere.
    """
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception as exc:
        # If psutil itself errors (uninstallable on a niche platform,
        # corrupt /proc, etc.), fall back to the os.kill check that
        # works correctly on Linux/macOS. Windows users who hit this
        # branch get the original buggy behavior — but at least Linux
        # users always self-heal.
        logger.warning(
            "psutil.pid_exists failed (%s: %s); falling back to os.kill",
            type(exc).__name__,
            exc,
        )
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError):
            return False
        except PermissionError:
            return True
        except OSError:
            return True


def _get_process_name(pid: int) -> str:
    """Best-effort process-name lookup for the unlock command's safety
    check. Returns empty string if unavailable on this platform / for
    this PID. Cross-platform via psutil; pre-fix this used a Linux-only
    /proc/<pid>/comm read."""
    if pid <= 0:
        return ""
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        return ""


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
    write_json_atomic(path, state.to_dict())


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
        except OSError:
            return False
        if pid_str:
            try:
                pid = int(pid_str)
            except ValueError:
                # Garbage in the lock file — treat as stale.
                pid = -1
            if pid > 0:
                if pid == os.getpid():
                    # Same process (e.g. dashboard wrote the lock with
                    # our PID before we started). Already ours — done.
                    return True
                if _pid_is_alive(pid):
                    # The PID is alive — but is it *us*? The OS recycles
                    # PIDs; a lock left behind by a crashed run can point
                    # at an unrelated process that happens to now own
                    # that PID. Pre-v0.4.4 that made the lock effectively
                    # permanent — ``urika run --resume`` failed after 0
                    # turns with a misleading "already running (PID N is
                    # alive)" until the user manually ran ``urika
                    # unlock``. If the live process clearly isn't a
                    # Python / urika process, treat the lock as stale.
                    proc_name = _get_process_name(pid).lower()
                    if proc_name and not (
                        "python" in proc_name or "urika" in proc_name
                    ):
                        logger.info(
                            "Lock for %s points at live PID %d (%s) which is "
                            "not a python/urika process — treating as stale.",
                            experiment_id,
                            pid,
                            proc_name,
                        )
                        # fall through to unlink below
                    else:
                        return False  # Looks like a real urika run — valid
                # PID is dead (or recycled to a non-urika process) —
                # fall through to unlink below.
        # Empty lock file: pre-v0.3 (commit 2fdae4b4) used
        # ``path.touch()`` which created empty locks; current release
        # ALWAYS writes the PID into the lock below. So any empty lock
        # is either (a) leftover from a pre-v0.3 release that crashed
        # before clean exit, or (b) (theoretically) a new lock racing
        # with a concurrent ``acquire_lock`` between create and write
        # — but ``write_text`` is fast enough that this is sub-
        # millisecond and the caller's protection loop would retry.
        # Either way the safest answer is "stale" — refusing for 6
        # hours after an old crash (the pre-v0.4.2 behaviour) caught
        # real users with brand-new releases bouncing off ancient
        # locks. See v0.4.2 Package K.
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
    # Local import (not top-level) because progress.update_experiment_status
    # imports load_progress which calls into this module's `_now_iso` / etc
    # transitively in test fixtures; the existing complete/fail/stop paths
    # already use the same local-import pattern.
    from urika.core.progress import update_experiment_status

    if not acquire_lock(project_dir, experiment_id):
        lock_pid = ""
        try:
            lock_pid = _lock_path(project_dir, experiment_id).read_text().strip()
        except OSError:
            pass
        if lock_pid:
            msg = (
                f"Experiment {experiment_id} is already running "
                f"(PID {lock_pid} is alive). If that PID is unrelated to "
                f"Urika (e.g. recycled by the OS), clear the stale lock "
                f"with: urika unlock {project_dir.name} {experiment_id}"
            )
        else:
            msg = (
                f"Experiment {experiment_id} is already running "
                f"(lock file present but unreadable). Clear it with: "
                f"urika unlock {project_dir.name} {experiment_id}"
            )
        raise RuntimeError(msg)

    state = SessionState(
        experiment_id=experiment_id,
        status="running",
        started_at=_now_iso(),
        max_turns=max_turns,
    )
    save_session(project_dir, experiment_id, state)
    # Mirror "running" into progress.json so ``urika status`` and the
    # CLI/dashboard's experiment listings stop showing "pending" for the
    # entire active lifetime of the run. Pre-fix, progress.json's status
    # field was only ever set on terminal states (completed / failed /
    # stopped), so a Windows user with a long-running experiment saw
    # "pending" for ~26 hours and had no CLI signal that work was
    # actually happening. session.json carried the right answer but
    # ``urika status`` reads progress.json, not session.json.
    try:
        update_experiment_status(project_dir, experiment_id, "running")
    except Exception as exc:
        logger.warning("Progress status mirror failed on start: %s", exc)
    return state


def pause_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Pause a running session. Updates status, removes lockfile."""
    from urika.core.progress import update_experiment_status

    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    state.status = "paused"
    state.paused_at = _now_iso()
    save_session(project_dir, experiment_id, state)
    release_lock(project_dir, experiment_id)
    try:
        update_experiment_status(project_dir, experiment_id, "paused")
    except Exception as exc:
        logger.warning("Progress status mirror failed on pause: %s", exc)
    return state


def resume_session(project_dir: Path, experiment_id: str) -> SessionState:
    """Resume a paused or failed session. Restores status to running, re-acquires lock."""
    from urika.core.progress import update_experiment_status

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
        try:
            update_experiment_status(project_dir, experiment_id, "running")
        except Exception as exc:
            logger.warning("Progress status mirror failed on resume: %s", exc)
        return state
    except Exception:
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
    """Mark session as stopped (deliberate user interruption). Removes lockfile.

    Refuses to downgrade a terminal state (``completed`` / ``failed`` /
    ``stopped``). v0.4.1 fix: pre-fix, a SIGTERM arriving AFTER
    ``complete_session`` had already run (e.g. the dashboard's Stop
    button clicked while ``_generate_reports`` was producing the
    per-experiment narrative) overwrote the on-disk ``completed``
    status with ``stopped`` and exited 1, making a successful run
    look like a failed one. The experiment had already met criteria
    by that point and ``progress.json`` already showed the success
    metrics — the report-generation pass is cosmetic.

    Lockfile is released regardless so a stuck terminal state never
    prevents future runs.
    """
    from urika.core.progress import update_experiment_status

    state = load_session(project_dir, experiment_id)
    if state is None:
        msg = f"No session found for experiment {experiment_id}"
        raise FileNotFoundError(msg)

    if state.status in ("completed", "failed", "stopped"):
        # Already terminal — release the lock but keep the existing
        # status. Use the reason field to record that a stop was
        # requested post-completion (useful for distinguishing a
        # "completed-narrative-pending" run from one that finished
        # cleanly).
        if reason is not None:
            state.checkpoint.setdefault("post_terminal_stop_reason", reason)
            save_session(project_dir, experiment_id, state)
        release_lock(project_dir, experiment_id)
        return state

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
