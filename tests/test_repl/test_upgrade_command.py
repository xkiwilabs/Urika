"""REPL ``/upgrade`` parity (v0.10.0 Phase 1).

The slash dispatches to the same ``urika upgrade`` Click command the CLI
exposes, so the migration logic stays single-sourced. The TUI inherits
the REPL registry, so a REPL test covers both surfaces.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from urika.core.models import ProjectConfig, current_schema_version
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace
from urika.repl.commands import GLOBAL_COMMANDS, cmd_upgrade
from urika.repl.session import ReplSession


def _legacy_project(tmp_path: Path, name: str) -> Path:
    """A project with no schema_version on disk (simulating a legacy one)."""
    project_dir = tmp_path / name
    create_project_workspace(
        project_dir,
        ProjectConfig(name=name, question="q", mode="exploratory", data_paths=[]),
    )
    # Strip the freshly-stamped schema_version so it looks legacy.
    toml = (project_dir / "urika.toml").read_text()
    lines = [ln for ln in toml.splitlines() if not ln.startswith("schema_version")]
    (project_dir / "urika.toml").write_text("\n".join(lines) + "\n")
    ProjectRegistry().register(name, project_dir)
    return project_dir


def _schema_version(project_dir: Path) -> str:
    with open(project_dir / "urika.toml", "rb") as f:
        return tomllib.load(f)["project"].get("schema_version", "")


def test_cmd_upgrade_registered_as_global_command() -> None:
    assert "upgrade" in GLOBAL_COMMANDS
    assert GLOBAL_COMMANDS["upgrade"]["func"] is cmd_upgrade


def test_upgrade_loaded_project(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = _legacy_project(tmp_path, "proj")
    assert _schema_version(project_dir) == ""

    session = ReplSession()
    session.load_project(path=project_dir, name="proj")

    cmd_upgrade(session, "")
    out = capsys.readouterr().out

    assert _schema_version(project_dir) == current_schema_version()
    assert "proj" in out


def test_upgrade_named_project(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = _legacy_project(tmp_path, "other")

    session = ReplSession()  # no project loaded
    cmd_upgrade(session, "other")
    capsys.readouterr()

    assert _schema_version(project_dir) == current_schema_version()


def test_upgrade_all(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    a = _legacy_project(tmp_path, "a")
    b = _legacy_project(tmp_path, "b")

    session = ReplSession()
    cmd_upgrade(session, "--all")
    capsys.readouterr()

    assert _schema_version(a) == current_schema_version()
    assert _schema_version(b) == current_schema_version()


def test_upgrade_no_project_no_all_prints_hint(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    session = ReplSession()  # no project loaded
    cmd_upgrade(session, "")
    out = capsys.readouterr().out
    assert "No project loaded" in out
