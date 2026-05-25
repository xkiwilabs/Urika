"""``/run --resume`` must be reachable from the LOCAL REPL/TUI input.

Pre-fix ``commands_run.py`` hardcoded ``resume=False`` in the
local-input ``ctx.invoke(cli_run, ...)`` path (only the remote
Slack/Telegram path threaded ``--resume`` through). A user typing
``/run --resume`` in the REPL/TUI could not resume.

These tests pin that the local typed ``--resume`` flag is parsed and
threaded into ``ctx.invoke(cli_run, ..., resume=True)``.
"""

from __future__ import annotations

from pathlib import Path

import click

from urika.repl.commands_run import cmd_run
from urika.repl.session import ReplSession


def _setup(tmp_path: Path) -> tuple[ReplSession, Path]:
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    create_experiment(proj, name="baseline", hypothesis="h")
    session = ReplSession()
    session.load_project(path=proj, name="alpha")
    return session, proj


def _capture_invoke(monkeypatch) -> dict:
    """Replace click.Context.invoke so cmd_run's dispatch is captured
    rather than executed. Returns a dict that gets the kwargs."""
    captured: dict = {}

    def _fake_invoke(self, _callback, *args, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return None

    monkeypatch.setattr(click.Context, "invoke", _fake_invoke, raising=True)
    return captured


def test_local_run_resume_threads_resume_true(tmp_path: Path, monkeypatch) -> None:
    session, _ = _setup(tmp_path)
    # Pick "Run with defaults" at the interactive menu.
    monkeypatch.setattr(
        "urika.repl.commands_run._prompt_numbered",
        lambda *a, **k: "Run with defaults",
    )
    captured = _capture_invoke(monkeypatch)

    cmd_run(session, "--resume")

    assert captured.get("resume") is True


def test_local_run_without_resume_is_false(tmp_path: Path, monkeypatch) -> None:
    session, _ = _setup(tmp_path)
    monkeypatch.setattr(
        "urika.repl.commands_run._prompt_numbered",
        lambda *a, **k: "Run with defaults",
    )
    captured = _capture_invoke(monkeypatch)

    cmd_run(session, "")

    assert captured.get("resume") is False
