"""REPL ``/config auto-capture`` parity (v0.7 cross-surface sweep).

The dashboard's memory page already toggles ``[memory] auto_capture``;
this slash gives REPL/TUI users the same surface without dropping to
``urika config auto-capture``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace
from urika.repl.commands import cmd_config
from urika.repl.session import ReplSession


def _setup(tmp_path: Path, monkeypatch) -> ReplSession:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="proj", question="q", mode="exploratory", data_paths=[]),
    )
    ProjectRegistry().register("proj", project_dir)
    session = ReplSession()
    session.load_project(path=project_dir, name="proj")
    return session


def _read_auto_capture(project_dir: Path) -> bool:
    with open(project_dir / "urika.toml", "rb") as f:
        data = tomllib.load(f)
    return bool(data.get("memory", {}).get("auto_capture", True))


def test_disable_writes_false(tmp_path, monkeypatch) -> None:
    session = _setup(tmp_path, monkeypatch)
    cmd_config(session, "auto-capture --disable")
    assert _read_auto_capture(session.project_path) is False


def test_enable_writes_true(tmp_path, monkeypatch) -> None:
    session = _setup(tmp_path, monkeypatch)
    cmd_config(session, "auto-capture --disable")
    cmd_config(session, "auto-capture --enable")
    assert _read_auto_capture(session.project_path) is True


def test_show_default_value(tmp_path, monkeypatch, capsys) -> None:
    """Bare ``/config auto-capture`` (no flag) prints the current state."""
    session = _setup(tmp_path, monkeypatch)
    cmd_config(session, "auto-capture")
    out = capsys.readouterr().out
    assert "auto_capture" in out
    assert "enabled" in out.lower()


def test_refuses_without_project(tmp_path, monkeypatch, capsys) -> None:
    """No loaded project: print a usage hint, don't crash."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    session = ReplSession()  # nothing loaded
    cmd_config(session, "auto-capture --enable")
    out = capsys.readouterr().out
    assert "needs a loaded project" in out or "Use /project" in out


def test_keeps_sibling_settings_intact(tmp_path, monkeypatch) -> None:
    """Toggling auto-capture must not clobber sibling TOML blocks
    (project/runtime). Mirrors the dashboard's shared ``_write_toml``
    helper invariant."""
    session = _setup(tmp_path, monkeypatch)
    cmd_config(session, "auto-capture --disable")

    with open(session.project_path / "urika.toml", "rb") as f:
        data = tomllib.load(f)
    assert data.get("project", {}).get("name") == "proj"
