"""Tests for the REPL ``/memory archive`` and ``/memory diff`` slash
sub-actions (v0.5.0 Task 3.3).

``cmd_memory`` dispatches to the underlying CLI commands via
``click.Context(...).invoke(...)``; T3.3 wires the two new sub-actions
that match the CLI counterparts added in T3.2.

For ``/memory diff <from> <to>`` we require two whitespace-free tokens
so the REPL doesn't need to do any quoting tricks. Multi-token
relative-time forms like ``1h ago`` must be written with an underscore
(``1h_ago``); the CLI parser strips the underscore back into a space.
"""

from __future__ import annotations

from pathlib import Path

import click

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace
from urika.repl.session import ReplSession


def _setup(tmp_path: Path, monkeypatch) -> ReplSession:
    """Mirror tests/test_repl/test_memory_curate.py's ``_setup`` pattern:
    register a real project and load it into a session."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    create_experiment(proj, name="baseline", hypothesis="h")
    ProjectRegistry().register("alpha", proj)
    session = ReplSession()
    session.load_project(path=proj, name="alpha")
    return session


def test_repl_memory_archive_dispatches(tmp_path, monkeypatch) -> None:
    """`/memory archive` calls the ``memory_archive`` CLI command."""
    captured: dict = {}

    def fake_invoke(self, cmd, *args, **kwargs):
        captured["cmd_name"] = cmd.name
        captured.update(kwargs)
        return None

    monkeypatch.setattr(click.Context, "invoke", fake_invoke)

    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "archive")
    assert captured["cmd_name"] == "archive"
    assert captured.get("project") == "alpha"
    assert captured.get("month") is None
    assert captured.get("json_output") is False


def test_repl_memory_archive_month_flag(tmp_path, monkeypatch) -> None:
    """`/memory archive --month 2024-01` propagates the month."""
    captured: dict = {}

    def fake_invoke(self, cmd, *args, **kwargs):
        captured["cmd_name"] = cmd.name
        captured.update(kwargs)
        return None

    monkeypatch.setattr(click.Context, "invoke", fake_invoke)

    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "archive --month 2024-01")
    assert captured["cmd_name"] == "archive"
    assert captured["month"] == "2024-01"


def test_repl_memory_diff_passes_timestamps(tmp_path, monkeypatch) -> None:
    """`/memory diff 1h_ago now` propagates both timestamps as-is."""
    captured: dict = {}

    def fake_invoke(self, cmd, *args, **kwargs):
        captured["cmd_name"] = cmd.name
        captured.update(kwargs)
        return None

    monkeypatch.setattr(click.Context, "invoke", fake_invoke)

    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "diff 1h_ago now")
    assert captured["cmd_name"] == "diff"
    assert captured["from_ts"] == "1h_ago"
    assert captured["to_ts"] == "now"
    assert captured.get("project") == "alpha"


def test_repl_memory_diff_missing_args(tmp_path, monkeypatch, capsys) -> None:
    """Too few args prints a usage line, doesn't crash."""
    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "diff now")  # only one arg
    out = capsys.readouterr().out
    assert "Usage" in out or "<from> <to>" in out


def test_repl_memory_archive_without_project_warns(
    tmp_path, monkeypatch, capsys
) -> None:
    """No project loaded → warn the user, don't crash."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from urika.repl.commands import cmd_memory

    session = ReplSession()
    cmd_memory(session, "archive")
    out = capsys.readouterr().out
    assert "No project loaded" in out


def test_repl_memory_unknown_subaction_lists_archive_and_diff(
    tmp_path, monkeypatch, capsys
) -> None:
    """The 'unknown subcommand' help line should mention ``archive``
    and ``diff`` so users discover them (regression guard)."""
    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "bogus-subaction-name")
    out = capsys.readouterr().out
    assert "archive" in out
    assert "diff" in out


def test_parse_relative_accepts_underscore() -> None:
    """The CLI parser must accept ``1h_ago`` so the REPL slash command
    can pass single-token relative times."""
    from datetime import datetime, timezone

    from urika.cli.memory import _parse_relative

    now = datetime.now(timezone.utc)
    parsed = _parse_relative("1h_ago")
    delta = now - parsed
    # Roughly 1 hour, give or take a few seconds of test runtime.
    assert 3500 < delta.total_seconds() < 3700


def test_parse_relative_accepts_space() -> None:
    """The original ``1h ago`` (with space) form still works."""
    from datetime import datetime, timezone

    from urika.cli.memory import _parse_relative

    now = datetime.now(timezone.utc)
    parsed = _parse_relative("2d ago")
    delta = now - parsed
    # 2 days = 172800s; allow a few seconds slop.
    assert 172700 < delta.total_seconds() < 172900
