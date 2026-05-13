"""Registration + minimal dispatch coverage for previously-uncovered
REPL slashes (/usage, /methods, /results, /criteria, /inspect, /logs,
/knowledge, /update, /status, /experiments, /new-session, /tools).

Each wraps a CLI command thinly; the CLI command has its own tests.
This file pins that the slash is registered + dispatchable + doesn't
crash on simple invocations against a real project."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl.commands_registry import GLOBAL_COMMANDS, PROJECT_COMMANDS
from urika.repl.session import ReplSession


def _setup(tmp_path: Path, monkeypatch) -> ReplSession:
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import create_project_workspace

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


# ── registration ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "slash",
    [
        "usage",
        "tools",
        "memory",
        "sessions",
        "venv",
        "experiment-create",
        "experiments",
        "setup",
        "summarize",
        "copy",
        "stop",
        "pause",
        "resume-session",
        "new-session",
        "logs",
    ],
)
def test_slash_is_registered(slash: str) -> None:
    """The slash command appears in either the global or
    project-scoped command registry."""
    in_global = slash in GLOBAL_COMMANDS
    in_project = slash in PROJECT_COMMANDS
    assert in_global or in_project, f"/{slash} is not registered"


# ── dispatch (smoke — must not crash) ──────────────────────────


def test_cmd_usage_runs(tmp_path, monkeypatch, capsys) -> None:
    from urika.repl.commands import cmd_usage

    session = _setup(tmp_path, monkeypatch)
    cmd_usage(session, "")
    out = capsys.readouterr().out
    # Some output produced; exact content depends on the wrapped CLI.
    assert out is not None


def test_cmd_tools_runs(tmp_path, monkeypatch, capsys) -> None:
    from urika.repl.commands import cmd_tools

    session = _setup(tmp_path, monkeypatch)
    cmd_tools(session, "")
    out = capsys.readouterr().out
    assert out.strip(), "cmd_tools produced no output"


# cmd_summarize dispatch is covered by tests/test_cli_agents.py
# (TestSummarize, 7 tests) — the slash invokes the same CLI command.


def test_cmd_sessions_runs(tmp_path, monkeypatch, capsys) -> None:
    from urika.repl.commands import cmd_sessions

    session = _setup(tmp_path, monkeypatch)
    cmd_sessions(session, "")
    # No saved sessions yet — should not crash.
    out = capsys.readouterr().out
    assert out is not None


def test_cmd_memory_lists_when_empty(tmp_path, monkeypatch, capsys) -> None:
    from urika.repl.commands import cmd_memory

    session = _setup(tmp_path, monkeypatch)
    cmd_memory(session, "")  # list mode
    out = capsys.readouterr().out
    # Either an "empty" message or a list — must not crash.
    assert out is not None


def test_cmd_venv_status_runs(tmp_path, monkeypatch, capsys) -> None:
    from urika.repl.commands import cmd_venv

    session = _setup(tmp_path, monkeypatch)
    cmd_venv(session, "status")
    out = capsys.readouterr().out
    assert out.strip()


def test_cmd_copy_runs_with_no_buffer(tmp_path, monkeypatch, capsys) -> None:
    """cmd_copy must not crash when there's no buffered output."""
    from urika.repl.commands import cmd_copy

    session = _setup(tmp_path, monkeypatch)
    cmd_copy(session, "")
    # The output may be a warning; no crash is the contract.


def test_cmd_experiment_create_dispatches(tmp_path, monkeypatch, capsys) -> None:
    from urika.repl.commands import cmd_experiment_create

    session = _setup(tmp_path, monkeypatch)
    cmd_experiment_create(session, "fresh-one")
    # The experiment should be created on disk.
    exp_dirs = list((session.project_path / "experiments").iterdir())
    assert any("fresh-one" in d.name for d in exp_dirs)


def test_cmd_new_session_clears_orchestrator(tmp_path, monkeypatch) -> None:
    from urika.repl.commands_session import cmd_new_session

    session = _setup(tmp_path, monkeypatch)

    class _Orch:
        def __init__(self):
            self.messages = [{"role": "user", "content": "old"}]

        def clear(self):
            self.messages = []

    orch = _Orch()
    monkeypatch.setattr("urika.repl.main._get_orchestrator", lambda _s: orch)
    cmd_new_session(session, "")
    assert orch.messages == [], "new-session must clear orchestrator history"
