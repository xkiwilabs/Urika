"""REPL /notifications and /config slash handlers.

Both wrap the corresponding CLI command via ``ctx.invoke``. Pre-this
file, both handlers were uninvoked by any test — registration only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl.commands import cmd_config, cmd_notifications
from urika.repl.session import ReplSession


@pytest.fixture
def urika_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


def _project_session(tmp_path: Path, urika_home: Path) -> ReplSession:
    from urika.core.models import ProjectConfig
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    ProjectRegistry().register("alpha", proj)
    session = ReplSession()
    session.load_project(path=proj, name="alpha")
    return session


# ── /config ────────────────────────────────────────────────────


def test_cmd_config_show_with_project_shows_project_config(
    tmp_path, urika_home, capsys
) -> None:
    session = _project_session(tmp_path, urika_home)
    cmd_config(session, "show")
    out = capsys.readouterr().out
    # Project name appears somewhere in the output.
    assert "alpha" in out or "exploratory" in out


def test_cmd_config_global_show(tmp_path, urika_home, capsys) -> None:
    session = ReplSession()  # no project
    cmd_config(session, "global show")
    out = capsys.readouterr().out
    # Must not raise; some output produced.
    assert out.strip(), "cmd_config global show produced no output"


# NOTE: ``cmd_config(session, "")`` with no project triggers the
# interactive privacy-mode wizard. Driving that here would duplicate
# the dedicated wizard tests in tests/test_cli_config.py; we cover the
# *dispatch* paths above and rely on the CLI tests for the wizard.


# ── /notifications ─────────────────────────────────────────────


def test_cmd_notifications_show_global(tmp_path, urika_home, capsys) -> None:
    session = ReplSession()  # no project
    cmd_notifications(session, "show")
    out = capsys.readouterr().out
    # Must not raise; some output produced (likely "not configured").
    assert out.strip()


def test_cmd_notifications_show_project_lists_channels(
    tmp_path, urika_home, capsys
) -> None:
    session = _project_session(tmp_path, urika_home)
    # Set up channels in the project's urika.toml.
    toml_path = session.project_path / "urika.toml"
    toml_path.write_text(
        toml_path.read_text() + '\n[notifications]\nchannels = ["email"]\n',
        encoding="utf-8",
    )
    cmd_notifications(session, "show")
    out = capsys.readouterr().out
    assert "alpha" in out.lower() or "email" in out.lower()


def test_cmd_notifications_test_with_no_config_does_not_crash(
    tmp_path, urika_home, capsys
) -> None:
    session = ReplSession()
    cmd_notifications(session, "test")
    # Must not raise / hang.
    assert capsys.readouterr().out.strip()
