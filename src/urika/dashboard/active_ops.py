"""Detect and describe currently-running agent operations for a project.

Single source of truth for which ``.lock`` files indicate a live
operation. UI buttons, the project banner, and the spawn endpoints
all read from here so they agree on what's running.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from urika.core.project_delete import _is_active_run_lock, _pid_is_alive


@dataclass(frozen=True)
class ActiveOp:
    """A running agent operation, located by its lock file."""

    type: str  # "run" | "evaluate" | "report" | "present" |
    # "summarize" | "finalize" | "build_tool"
    project_name: str
    experiment_id: str | None  # None for project-level ops
    lock_path: Path
    log_url: str  # absolute path under /projects/...


# Lock-file shapes we know about. Order matters only for the
# experiment-level "more specific first" rule — match longer suffixes
# before bare ".lock".
_PROJECT_LEVEL_LOCKS: tuple[tuple[str, str, str], ...] = (
    # (lock relative path, op type, log url template — uses {project} placeholder)
    ("projectbook/.finalize.lock", "finalize", "/projects/{project}/finalize/log"),
    ("projectbook/.summarize.lock", "summarize", "/projects/{project}/summarize/log"),
    ("tools/.build.lock", "build_tool", "/projects/{project}/tools/build/log"),
)

_EXPERIMENT_LEVEL_LOCKS: tuple[tuple[str, str, str | None], ...] = (
    # (lock filename within experiments/<id>/, op type, log query type or
    # None for the bare run lock).
    (".evaluate.lock", "evaluate", "evaluate"),
    (".report.lock", "report", "report"),
    (".present.lock", "present", "present"),
    (".lock", "run", None),  # bare .lock is the experiment run; check last
)


def list_active_operations(project_name: str, project_path: Path) -> list[ActiveOp]:
    """Walk known lock shapes; return only those with a live PID.

    The helper is called on every project-page render, so it stays
    cheap: a fixed set of stat calls for project-level locks plus one
    ``iterdir()`` over ``experiments/`` (skipped if absent).
    """
    if not project_path.exists():
        return []

    ops: list[ActiveOp] = []

    # Project-level locks at fixed paths.
    for rel, op_type, url_template in _PROJECT_LEVEL_LOCKS:
        lock = project_path / rel
        if lock.is_file() and _is_active_run_lock(lock):
            ops.append(
                ActiveOp(
                    type=op_type,
                    project_name=project_name,
                    experiment_id=None,
                    lock_path=lock,
                    log_url=url_template.format(project=project_name),
                )
            )

    # Per-experiment locks. Scan experiments/<id>/<lockname>.
    exp_root = project_path / "experiments"
    if exp_root.is_dir():
        for exp_dir in exp_root.iterdir():
            if not exp_dir.is_dir():
                continue
            for lock_name, op_type, log_type in _EXPERIMENT_LEVEL_LOCKS:
                lock = exp_dir / lock_name
                if lock.is_file() and _is_active_run_lock(lock):
                    base = f"/projects/{project_name}/experiments/{exp_dir.name}/log"
                    log_url = base if log_type is None else f"{base}?type={log_type}"
                    ops.append(
                        ActiveOp(
                            type=op_type,
                            project_name=project_name,
                            experiment_id=exp_dir.name,
                            lock_path=lock,
                            log_url=log_url,
                        )
                    )
                    # Locks are exclusive: at most one op per
                    # experiment dir. More-specific suffix wins thanks
                    # to ordering above.
                    break

    return ops


@dataclass(frozen=True)
class ClearedLock:
    """A run-lock file that ``clear_stale_locks`` removed."""

    path: Path
    pid: int | None  # None when the file was empty / non-numeric
    reason: str       # "dead" | "empty" | "non-numeric"


def _all_known_lock_paths(project_path: Path) -> list[Path]:
    """Every spot we know agents drop run-locks. Used by stale-clear."""
    paths: list[Path] = []
    for rel, _op_type, _url in _PROJECT_LEVEL_LOCKS:
        paths.append(project_path / rel)
    exp_root = project_path / "experiments"
    if exp_root.is_dir():
        for exp_dir in exp_root.iterdir():
            if not exp_dir.is_dir():
                continue
            for lock_name, _op_type, _log_type in _EXPERIMENT_LEVEL_LOCKS:
                paths.append(exp_dir / lock_name)
    return paths


def clear_stale_locks(project_path: Path) -> list[ClearedLock]:
    """Remove run-lock files that no longer correspond to a live PID.

    Walks every known lock location. For each existing lock file:
    - empty file → remove (no PID was ever written; agent crashed
      between create + write_text)
    - non-numeric content → remove (corrupted)
    - PID present but ``os.kill(pid, 0)`` says the process is dead →
      remove

    Live-PID locks are LEFT ALONE. If a user has a real running agent
    they don't want it killed by accident; the equivalent of ``kill``
    isn't this helper's job.

    Returns the list of files removed so the caller can surface them
    to the user.
    """
    cleared: list[ClearedLock] = []
    if not project_path.exists():
        return cleared

    for lock in _all_known_lock_paths(project_path):
        if not lock.is_file():
            continue
        try:
            content = lock.read_text(encoding="utf-8").strip()
        except OSError:
            # Treat unreadable locks as live to avoid accidental
            # destruction; user can fall back to terminal.
            continue
        if not content:
            try:
                lock.unlink()
                cleared.append(ClearedLock(path=lock, pid=None, reason="empty"))
            except OSError:
                pass
            continue
        try:
            pid = int(content)
        except ValueError:
            try:
                lock.unlink()
                cleared.append(ClearedLock(path=lock, pid=None, reason="non-numeric"))
            except OSError:
                pass
            continue
        if not _pid_is_alive(pid):
            try:
                lock.unlink()
                cleared.append(ClearedLock(path=lock, pid=pid, reason="dead"))
            except OSError:
                pass
    return cleared
