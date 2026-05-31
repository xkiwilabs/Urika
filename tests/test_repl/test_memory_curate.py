"""Tests for the REPL ``/memory curate [--apply]`` slash sub-action
(v0.5.0 Task 2.9).

``cmd_memory`` already dispatches to the underlying CLI commands via
``click.Context(...).invoke(...)``; T2.9 just adds the ``curate``
sub-action that wires to the new ``memory_curate`` CLI subcommand.

We monkeypatch ``click.Context.invoke`` so the REPL test runs in
isolation from the real agent runner.
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
    """Mirror tests/test_repl/test_uncovered_slashes.py's ``_setup``
    pattern: register a real project and load it into a session."""
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


def test_repl_memory_curate_dry_run_invokes_cli(tmp_path, monkeypatch) -> None:
    """`/memory curate` (no flags) calls the ``memory_curate`` CLI
    command via ``click.Context.invoke`` with apply_changes=False."""
    captured: dict = {}

    def fake_invoke(self, cmd, *args, **kwargs):
        captured["cmd_name"] = cmd.name
        captured.update(kwargs)
        return None

    monkeypatch.setattr(click.Context, "invoke", fake_invoke)

    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "curate")
    assert captured["cmd_name"] == "curate"
    assert captured.get("project") == "alpha"
    assert captured.get("apply_changes") is False


def test_repl_memory_curate_apply_flag(tmp_path, monkeypatch) -> None:
    """`/memory curate --apply` propagates apply_changes=True to the
    underlying CLI command."""
    captured: dict = {}

    def fake_invoke(self, cmd, *args, **kwargs):
        captured["cmd_name"] = cmd.name
        captured.update(kwargs)
        return None

    monkeypatch.setattr(click.Context, "invoke", fake_invoke)

    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "curate --apply")
    assert captured["cmd_name"] == "curate"
    assert captured.get("project") == "alpha"
    assert captured.get("apply_changes") is True


def test_repl_memory_curate_without_project_warns(
    tmp_path, monkeypatch, capsys
) -> None:
    """No project loaded → warn the user, don't crash."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    from urika.repl.commands import cmd_memory

    session = ReplSession()
    cmd_memory(session, "curate")
    out = capsys.readouterr().out
    assert "No project loaded" in out


def test_repl_memory_unknown_subaction_lists_curate(
    tmp_path, monkeypatch, capsys
) -> None:
    """The 'unknown subcommand' help line should mention ``curate``
    so users discover it (regression guard: keeps the help text in
    sync with the dispatch table)."""
    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "bogus-subaction-name")
    out = capsys.readouterr().out
    assert "curate" in out


def test_repl_memory_curate_works_from_running_event_loop(
    tmp_path, monkeypatch
) -> None:
    """Regression: ``/memory curate`` must work when dispatched from
    inside an already-running event loop (REPL/TUI case), not just
    from CliRunner.

    Pre-fix the CLI subcommand called ``asyncio.run(run_curator(...))``
    unconditionally. When the REPL/TUI dispatched ``/memory curate`` on
    its own event loop, that raised
    ``RuntimeError: asyncio.run() cannot be called from a running event
    loop``. The earlier tests in this file monkeypatch
    ``click.Context.invoke`` so they bypass the body of the CLI command
    and never trip the collision. This test drives ``cmd_memory``
    through the real Click invocation path while the caller is inside
    ``asyncio.run(driver())`` — reproducing the bug exactly.
    """
    import asyncio

    from urika.core import memory_curator as _curator_mod
    from urika.core.memory_curator import CuratorResult

    session = _setup(tmp_path, monkeypatch)

    async def fake(project_dir, runner, apply=False):
        return CuratorResult(decisions=[], applied=False)

    monkeypatch.setattr(_curator_mod, "run_curator", fake)

    from urika.repl.commands import cmd_memory

    async def driver():
        # Must NOT raise:
        #   RuntimeError: asyncio.run() cannot be called from a
        #   running event loop
        cmd_memory(session, "curate")

    # ``asyncio.run`` here simulates the REPL/TUI's already-running
    # main loop. Any leaked asyncio.run inside the CLI subcommand
    # would bubble out and fail the test.
    asyncio.run(driver())
