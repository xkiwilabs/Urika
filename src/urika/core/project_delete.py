"""Move (trash) a registered project to ``~/.urika/trash/``.

Trashing is non-destructive: the project tree is moved (not deleted), a
manifest is written at the trash dir root, and a single line is appended to
``~/.urika/deletion-log.jsonl``. Active runs (any ``.lock`` file under the
project) block the operation.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from urika.core.registry import ProjectRegistry, _urika_home

MANIFEST_NAME = ".urika-trash-manifest.json"


class ProjectNotFoundError(Exception):
    """Project name is not in the registry."""


class ActiveRunError(Exception):
    """A ``.lock`` file under the project blocks deletion."""

    def __init__(self, lock_path: Path) -> None:
        super().__init__(f"Active run lock found at {lock_path}; stop the run first.")
        self.lock_path = lock_path


@dataclass
class TrashResult:
    """Outcome of a :func:`trash_project` call."""

    name: str
    original_path: Path
    trash_path: Path | None
    registry_only: bool


def _trash_root() -> Path:
    return _urika_home() / "trash"


def _deletion_log() -> Path:
    return _urika_home() / "deletion-log.jsonl"


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Signal blocked but the PID exists — treat as alive.
        return True
    except OSError:
        return False
    return True


def _is_active_run_lock(lock: Path) -> bool:
    """Return True only for live run-lock PID files.

    Urika writes two distinct kinds of ``.lock`` files:

    * Run/finalize/evaluate/etc. PID locks. Always dot-prefixed
      (``.lock``, ``.finalize.lock``, ``.evaluate.lock``, …) and
      contain a PID. The drainer thread removes them on subprocess
      exit, but a hard kill can leave them stale.
    * JSON write mutexes from ``urika.core.filelock`` (e.g.
      ``criteria.json.lock``, ``usage.json.lock``). Not dot-prefixed,
      always present once touched, and never indicate ongoing work.

    Only the first kind blocks deletion, and only when the recorded
    PID is still alive.
    """
    if not lock.is_file() or not lock.name.startswith("."):
        return False
    try:
        content = lock.read_text(encoding="utf-8").strip()
    except OSError:
        # Treat unreadable as active — safer than letting the user
        # accidentally trash a project mid-run.
        return True
    if not content:
        return False
    try:
        pid = int(content)
    except ValueError:
        return False
    return _pid_is_alive(pid)


def _find_active_lock(project_path: Path) -> Path | None:
    for lock in project_path.rglob("*.lock"):
        if _is_active_run_lock(lock):
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
    """Move a registered project to ``~/.urika/trash/`` and unregister it.

    If the project's folder is already missing, only the registry entry is
    removed (``registry_only=True``). Active ``.lock`` files anywhere under
    the project raise :class:`ActiveRunError` without modifying anything.
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
