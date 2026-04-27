"""Move (trash) an experiment within a project.

Mirrors :mod:`urika.core.project_delete` but scoped to a single experiment
directory. The experiment tree is moved (not deleted) into a project-local
``trash/`` directory at ``<project>/trash/<exp_id>-<YYYYMMDD-HHMMSS>/``;
a manifest is written at the trash dir root, and a single line is
appended to ``~/.urika/deletion-log.jsonl`` with ``kind: "experiment"``.
Active runs (any live ``.lock`` file under the experiment) block the
operation.

Project-local trash (rather than ``~/.urika/trash/``) keeps related work
together, survives project rename/move, and avoids cross-project name
collisions in a global trash dir.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from urika.core.project_delete import (
    MANIFEST_NAME,
    _find_active_lock,
    _timestamp,
    _urika_home,
)


class ExperimentNotFoundError(Exception):
    """Experiment directory does not exist under ``<project>/experiments/``."""


class ActiveExperimentError(Exception):
    """A live ``.lock`` file under the experiment blocks deletion."""

    def __init__(self, lock_path: Path) -> None:
        super().__init__(f"Active run lock found at {lock_path}; stop the run first.")
        self.lock_path = lock_path


@dataclass(frozen=True)
class TrashExperimentResult:
    """Outcome of a :func:`trash_experiment` call."""

    project_name: str
    experiment_id: str
    original_path: Path
    trash_path: Path


def _deletion_log() -> Path:
    return _urika_home() / "deletion-log.jsonl"


def _write_manifest(
    exp_path: Path,
    project_name: str,
    experiment_id: str,
    original_path: Path,
) -> None:
    from urika import __version__

    manifest = {
        "kind": "experiment",
        "project_name": project_name,
        "experiment_id": experiment_id,
        "original_path": str(original_path),
        "trashed_at": datetime.now(timezone.utc).isoformat(),
        "urika_version": __version__,
    }
    (exp_path / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def _append_deletion_log(entry: dict) -> None:
    log = _deletion_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def trash_experiment(
    project_path: Path,
    project_name: str,
    experiment_id: str,
) -> TrashExperimentResult:
    """Move an experiment to ``<project>/trash/`` and return the result.

    Raises:
        ExperimentNotFoundError: if ``<project>/experiments/<exp_id>`` is
            not a directory.
        ActiveExperimentError: if any live run-lock PID file is present
            under the experiment tree. Registry/folder are left
            untouched.
    """
    exp_dir = project_path / "experiments" / experiment_id
    if not exp_dir.is_dir():
        raise ExperimentNotFoundError(experiment_id)

    lock = _find_active_lock(exp_dir)
    if lock is not None:
        raise ActiveExperimentError(lock)

    _write_manifest(exp_dir, project_name, experiment_id, exp_dir)

    trash_root = project_path / "trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    trash_path = trash_root / f"{experiment_id}-{_timestamp()}"
    # Guard against same-second collisions (two trashes within one second).
    counter = 1
    while trash_path.exists():
        trash_path = trash_root / f"{experiment_id}-{_timestamp()}-{counter}"
        counter += 1

    shutil.move(str(exp_dir), str(trash_path))

    _append_deletion_log(
        {
            "kind": "experiment",
            "project_name": project_name,
            "experiment_id": experiment_id,
            "original_path": str(exp_dir),
            "trash_path": str(trash_path),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )

    return TrashExperimentResult(
        project_name=project_name,
        experiment_id=experiment_id,
        original_path=exp_dir,
        trash_path=trash_path,
    )
