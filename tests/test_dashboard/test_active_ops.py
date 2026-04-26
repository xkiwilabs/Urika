"""Tests for the active-operations dashboard helper."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from urika.dashboard.active_ops import ActiveOp, list_active_operations


def _write_lock(path: Path, pid: int | str) -> None:
    """Write a PID lock file at ``path``, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _make_project(root: Path, name: str = "foo") -> Path:
    project = root / name
    project.mkdir()
    return project


@pytest.fixture
def project_path(tmp_path: Path, tmp_urika_home: Path) -> Path:
    return _make_project(tmp_path)


def test_no_locks_returns_empty(project_path: Path) -> None:
    assert list_active_operations("foo", project_path) == []


def test_live_summarize_lock_returned(project_path: Path) -> None:
    lock = project_path / "projectbook" / ".summarize.lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, ActiveOp)
    assert op.type == "summarize"
    assert op.project_name == "foo"
    assert op.experiment_id is None
    assert op.lock_path == lock
    assert op.log_url == "/projects/foo/summarize/log"


def test_live_finalize_lock_returned(project_path: Path) -> None:
    lock = project_path / "projectbook" / ".finalize.lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert op.type == "finalize"
    assert op.experiment_id is None
    assert op.lock_path == lock
    assert op.log_url == "/projects/foo/finalize/log"


def test_live_build_tool_lock_returned(project_path: Path) -> None:
    lock = project_path / "tools" / ".build.lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert op.type == "build_tool"
    assert op.experiment_id is None
    assert op.lock_path == lock
    assert op.log_url.endswith("/tools/build/log")
    assert op.log_url == "/projects/foo/tools/build/log"


def test_live_run_lock_returned(project_path: Path) -> None:
    lock = project_path / "experiments" / "exp-001" / ".lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert op.type == "run"
    assert op.experiment_id == "exp-001"
    assert op.lock_path == lock
    assert op.log_url == "/projects/foo/experiments/exp-001/log"


def test_live_evaluate_lock_returned(project_path: Path) -> None:
    lock = project_path / "experiments" / "exp-001" / ".evaluate.lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert op.type == "evaluate"
    assert op.experiment_id == "exp-001"
    assert op.log_url == "/projects/foo/experiments/exp-001/log?type=evaluate"


def test_live_report_lock_returned(project_path: Path) -> None:
    lock = project_path / "experiments" / "exp-001" / ".report.lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert op.type == "report"
    assert op.experiment_id == "exp-001"
    assert op.log_url == "/projects/foo/experiments/exp-001/log?type=report"


def test_live_present_lock_returned(project_path: Path) -> None:
    lock = project_path / "experiments" / "exp-001" / ".present.lock"
    _write_lock(lock, os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    op = ops[0]
    assert op.type == "present"
    assert op.experiment_id == "exp-001"
    assert op.log_url == "/projects/foo/experiments/exp-001/log?type=present"


def test_stale_lock_not_returned(project_path: Path) -> None:
    lock = project_path / "projectbook" / ".summarize.lock"
    _write_lock(lock, 99999999)

    assert list_active_operations("foo", project_path) == []


def test_empty_lock_file_not_returned(project_path: Path) -> None:
    lock = project_path / "projectbook" / ".summarize.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()

    assert list_active_operations("foo", project_path) == []


def test_filelock_mutex_not_returned(project_path: Path) -> None:
    # filelock writes mutexes WITHOUT a leading dot in the basename
    # (e.g. criteria.json.lock). These must be ignored regardless of
    # contents.
    mutex = project_path / "criteria.json.lock"
    _write_lock(mutex, os.getpid())

    assert list_active_operations("foo", project_path) == []


def test_multiple_concurrent_ops_all_returned(project_path: Path) -> None:
    _write_lock(project_path / "projectbook" / ".summarize.lock", os.getpid())
    _write_lock(project_path / "experiments" / "exp-001" / ".lock", os.getpid())
    _write_lock(project_path / "tools" / ".build.lock", os.getpid())

    ops = sorted(list_active_operations("foo", project_path), key=lambda o: o.type)

    types = [op.type for op in ops]
    assert types == ["build_tool", "run", "summarize"]


def test_one_op_per_experiment_dir(project_path: Path) -> None:
    # Both .lock and .evaluate.lock present in the same exp dir. The
    # more-specific match (.evaluate.lock) wins.
    exp_dir = project_path / "experiments" / "exp-001"
    _write_lock(exp_dir / ".lock", os.getpid())
    _write_lock(exp_dir / ".evaluate.lock", os.getpid())

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    assert ops[0].type == "evaluate"
    assert ops[0].experiment_id == "exp-001"


def test_missing_project_path_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list_active_operations("foo", missing) == []


def test_no_experiments_dir_skipped_cleanly(project_path: Path) -> None:
    _write_lock(project_path / "projectbook" / ".summarize.lock", os.getpid())
    # No experiments/ dir at all.
    assert not (project_path / "experiments").exists()

    ops = list_active_operations("foo", project_path)

    assert len(ops) == 1
    assert ops[0].type == "summarize"
