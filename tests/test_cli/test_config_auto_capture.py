"""Tests for ``urika config auto-capture`` (v0.7 cross-surface sweep).

Pre-sweep the v0.5 ``[memory] auto_capture`` flag was only reachable
from the dashboard's memory page checkbox — CLI users had to hand-edit
``urika.toml``. This subcommand mirrors the dashboard write path.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace


def _setup(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="proj", question="q", mode="exploratory", data_paths=[]),
    )
    ProjectRegistry().register("proj", project_dir)
    return project_dir


def _read_auto_capture(project_dir: Path) -> bool:
    """Return the current value from urika.toml (default True when unset)."""
    with open(project_dir / "urika.toml", "rb") as f:
        data = tomllib.load(f)
    return bool(data.get("memory", {}).get("auto_capture", True))


def test_disable_writes_false(tmp_path: Path, monkeypatch) -> None:
    project = _setup(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["config", "auto-capture", "proj", "--disable"])
    assert result.exit_code == 0, result.output
    assert _read_auto_capture(project) is False
    assert "disabled" in result.output.lower()


def test_enable_writes_true(tmp_path: Path, monkeypatch) -> None:
    project = _setup(tmp_path, monkeypatch)

    # First disable so we can observe the enable transition.
    CliRunner().invoke(cli, ["config", "auto-capture", "proj", "--disable"])
    result = CliRunner().invoke(cli, ["config", "auto-capture", "proj", "--enable"])
    assert result.exit_code == 0, result.output
    assert _read_auto_capture(project) is True
    assert "enabled" in result.output.lower()


def test_show_default_value(tmp_path: Path, monkeypatch) -> None:
    """No --enable / --disable: print the current value. Default is True."""
    _setup(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["config", "auto-capture", "proj"])
    assert result.exit_code == 0, result.output
    assert "enabled" in result.output.lower()


def test_idempotent_no_change(tmp_path: Path, monkeypatch) -> None:
    """Asking for the current state should not re-write the file."""
    _setup(tmp_path, monkeypatch)

    CliRunner().invoke(cli, ["config", "auto-capture", "proj", "--disable"])
    result = CliRunner().invoke(cli, ["config", "auto-capture", "proj", "--disable"])
    assert result.exit_code == 0
    assert "already" in result.output.lower()


def test_persists_alongside_other_settings(tmp_path: Path, monkeypatch) -> None:
    """The toggle must not clobber sibling ``[project]`` / ``[runtime]``
    blocks — paired with the dashboard write path which uses the same
    ``_write_toml`` helper."""
    project = _setup(tmp_path, monkeypatch)

    CliRunner().invoke(cli, ["config", "auto-capture", "proj", "--disable"])

    with open(project / "urika.toml", "rb") as f:
        data = tomllib.load(f)

    # Project block kept intact.
    assert data.get("project", {}).get("name") == "proj"
    # And the new memory.auto_capture entry is there.
    assert data["memory"]["auto_capture"] is False


def test_auto_picks_single_project(tmp_path: Path, monkeypatch) -> None:
    """When there's exactly one registered project, the command picks
    it automatically (via ``_ensure_project``) — matching the rest of
    the CLI's UX for single-project users."""
    project = _setup(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["config", "auto-capture", "--disable"])
    assert result.exit_code == 0, result.output
    assert _read_auto_capture(project) is False
