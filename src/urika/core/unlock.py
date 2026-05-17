"""Stale-lock recovery — shared logic for CLI / REPL / TUI / dashboard.

v0.4.5 Track 2 extraction. Pre-fix the PID-aware safety logic lived
inline in ``cli/data.py:594-700`` (the ``urika unlock`` command).
That meant TUI / REPL / dashboard users either had no recovery
path at all or had to shell out to the CLI. The dashboard could
``clear_stale_locks`` only for *dead* PIDs (active_ops.py); the
``--force`` path that handles live-but-recycled PIDs was CLI-only.

This module centralises the decision: given a project + experiment
+ optional force, classify the lock and return a structured
result. Each surface renders the result in its own idiom (CLI =
click.echo; REPL = print_*; TUI = panel update; dashboard = JSON).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class UnlockStatus(str, Enum):
    """Outcome of ``try_unlock``. The string values are stable so
    JSON consumers (dashboard, RPC) can branch on them."""

    CLEARED = "cleared"
    # Lock removed successfully (PID was dead, OR force was True).

    NO_LOCK = "no_lock"
    # No lock file at the expected path — nothing to do.

    REFUSED_LIVE_URIKA = "refused_live_urika"
    # Lock owner PID is alive AND its process name looks like a real
    # urika/python process. Without ``force``, refuse to unlink —
    # we'd be killing someone's actual run.

    REFUSED_LIVE_OTHER = "refused_live_other"
    # Lock owner PID is alive but the process name doesn't look
    # like urika — almost certainly a recycled PID. Still refuse
    # without ``force`` so the user explicitly confirms.

    READ_FAILED = "read_failed"
    # Could not read the lock file at all (permissions, FS error).

    REMOVE_FAILED = "remove_failed"
    # Tried to unlink but the OS refused (permissions, FS error).


@dataclass(frozen=True)
class UnlockResult:
    """What ``try_unlock`` returns. Surfaces render this however they
    like; the ``status`` enum + ``pid`` + ``proc_name`` carry the
    full audit information."""

    status: UnlockStatus
    experiment_id: str
    lock_path: Path
    pid: int | None = None
    # Best-effort process name when the PID was alive. Empty string
    # when not applicable (PID dead / lock unreadable / no PID).
    proc_name: str = ""
    # OS error string when status is READ_FAILED / REMOVE_FAILED;
    # empty otherwise.
    error: str = ""


def try_unlock(
    project_path: Path,
    experiment_id: str,
    *,
    force: bool = False,
) -> UnlockResult:
    """Inspect the experiment's lock and (maybe) remove it.

    Semantics match the pre-extraction CLI behaviour exactly so the
    existing ``urika unlock`` tests still pass:

    1. No lock file → ``NO_LOCK`` (no-op).
    2. Lock contains garbage / empty / negative PID → treat as
       stale, unlink → ``CLEARED``.
    3. Lock contains a live PID:
       - process name looks like urika/python → ``REFUSED_LIVE_URIKA``
         (unless ``force``, in which case → ``CLEARED``).
       - process name doesn't look like urika → ``REFUSED_LIVE_OTHER``
         (unless ``force``, in which case → ``CLEARED``).
    4. Lock contains a dead PID → unlink → ``CLEARED``.

    Errors reading or unlinking the file surface as ``READ_FAILED``
    / ``REMOVE_FAILED`` with the OS error string attached so callers
    can show it; the caller decides how to render it.

    Cross-platform via ``urika.core.session._pid_is_alive`` (psutil).
    """
    # Local import: avoids a circular dependency at module load
    # (session.py → progress.py → workspace.py → ...).
    from urika.core.session import _get_process_name, _lock_path, _pid_is_alive

    lock_path = _lock_path(project_path, experiment_id)
    if not lock_path.exists():
        return UnlockResult(
            status=UnlockStatus.NO_LOCK,
            experiment_id=experiment_id,
            lock_path=lock_path,
        )

    try:
        pid_str = lock_path.read_text().strip()
    except OSError as exc:
        return UnlockResult(
            status=UnlockStatus.READ_FAILED,
            experiment_id=experiment_id,
            lock_path=lock_path,
            error=str(exc),
        )

    pid: int | None = None
    if pid_str:
        try:
            pid = int(pid_str)
        except ValueError:
            pid = None

    pid_alive = False
    proc_name = ""
    if pid is not None and pid > 0:
        pid_alive = _pid_is_alive(pid)
        if pid_alive:
            proc_name = _get_process_name(pid)

    if pid_alive and not force:
        looks_like_urika = bool(re.search(r"urika|python", proc_name, re.I))
        return UnlockResult(
            status=(
                UnlockStatus.REFUSED_LIVE_URIKA
                if looks_like_urika
                else UnlockStatus.REFUSED_LIVE_OTHER
            ),
            experiment_id=experiment_id,
            lock_path=lock_path,
            pid=pid,
            proc_name=proc_name,
        )

    # Dead PID, garbage PID, empty lock, or ``force``: unlink.
    try:
        lock_path.unlink()
    except OSError as exc:
        return UnlockResult(
            status=UnlockStatus.REMOVE_FAILED,
            experiment_id=experiment_id,
            lock_path=lock_path,
            pid=pid,
            proc_name=proc_name,
            error=str(exc),
        )

    return UnlockResult(
        status=UnlockStatus.CLEARED,
        experiment_id=experiment_id,
        lock_path=lock_path,
        pid=pid,
        proc_name=proc_name,
    )


def list_locked_experiments(project_path: Path) -> list[str]:
    """Return experiment IDs whose ``.lock`` file currently exists.

    Pure file-system listing — no PID liveness check. Use
    ``try_unlock`` per experiment to decide if a lock is actually
    stale. Shared by every surface's "pick which lock to clear"
    UI affordance.
    """
    from urika.core.experiment import list_experiments
    from urika.core.session import _lock_path

    experiments = list_experiments(project_path)
    return [
        e.experiment_id
        for e in experiments
        if _lock_path(project_path, e.experiment_id).exists()
    ]
