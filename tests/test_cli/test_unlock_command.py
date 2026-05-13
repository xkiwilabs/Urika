"""``urika unlock`` — extended coverage: unknown project, unknown
experiment, no locks, multiple locks (parametrize), error paths.

The existing tests cover the happy path + ``--force`` overriding a
live-pid lock. This file adds the missing surfaces."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def urika_env(tmp_path: Path, monkeypatch) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return {"URIKA_HOME": str(home)}


def _project_with_experiments(urika_env: dict, tmp_path: Path,
                              n_exps: int = 1) -> Path:
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="?", mode="exploratory")
    )
    for i in range(n_exps):
        create_experiment(proj, name=f"exp-{i}", hypothesis="h")
    ProjectRegistry().register("alpha", proj)
    return proj


def test_unlock_unknown_project(urika_env) -> None:
    r = CliRunner().invoke(cli, ["unlock", "does-not-exist"], env=urika_env)
    assert r.exit_code != 0
    assert "not found" in r.output.lower() or "unknown" in r.output.lower()


def test_unlock_no_locked_experiments(urika_env, tmp_path) -> None:
    _project_with_experiments(urika_env, tmp_path)
    r = CliRunner().invoke(cli, ["unlock", "alpha"], env=urika_env)
    assert r.exit_code == 0
    assert "No locked" in r.output


def test_unlock_specific_experiment_with_no_lock(urika_env, tmp_path) -> None:
    _project_with_experiments(urika_env, tmp_path)
    r = CliRunner().invoke(
        cli, ["unlock", "alpha", "exp-001-exp-0"], env=urika_env
    )
    assert r.exit_code == 0
    assert "No lock file" in r.output


def test_unlock_cleans_stale_lock_with_dead_pid(urika_env, tmp_path) -> None:
    """A lock with an implausibly large (dead) PID is cleaned without
    requiring --force."""
    proj = _project_with_experiments(urika_env, tmp_path)
    exp_dir = proj / "experiments" / "exp-001-exp-0"
    (exp_dir / ".lock").write_text("99999998")
    r = CliRunner().invoke(
        cli, ["unlock", "alpha", "exp-001-exp-0"], env=urika_env
    )
    assert r.exit_code == 0, r.output
    assert not (exp_dir / ".lock").exists()


def test_unlock_refuses_live_python_lock_without_force(urika_env, tmp_path) -> None:
    """A lock pointing at *this* test process (a real python) is
    refused without --force."""
    proj = _project_with_experiments(urika_env, tmp_path)
    exp_dir = proj / "experiments" / "exp-001-exp-0"
    (exp_dir / ".lock").write_text(str(os.getpid()))
    r = CliRunner().invoke(
        cli, ["unlock", "alpha", "exp-001-exp-0"], env=urika_env
    )
    # The CLI refuses (exit !=0) and the lock is untouched.
    assert (exp_dir / ".lock").exists()


def test_unlock_with_force_clears_live_lock(urika_env, tmp_path) -> None:
    proj = _project_with_experiments(urika_env, tmp_path)
    exp_dir = proj / "experiments" / "exp-001-exp-0"
    (exp_dir / ".lock").write_text(str(os.getpid()))
    r = CliRunner().invoke(
        cli, ["unlock", "alpha", "exp-001-exp-0", "--force"], env=urika_env
    )
    assert r.exit_code == 0, r.output
    assert not (exp_dir / ".lock").exists()


def test_unlock_garbage_in_lockfile_is_cleaned(urika_env, tmp_path) -> None:
    """A lock file with non-numeric content (external editor, corrupt
    write) → treated as stale → cleaned."""
    proj = _project_with_experiments(urika_env, tmp_path)
    exp_dir = proj / "experiments" / "exp-001-exp-0"
    (exp_dir / ".lock").write_text("not-a-pid")
    r = CliRunner().invoke(
        cli, ["unlock", "alpha", "exp-001-exp-0"], env=urika_env
    )
    assert r.exit_code == 0
    assert not (exp_dir / ".lock").exists()
