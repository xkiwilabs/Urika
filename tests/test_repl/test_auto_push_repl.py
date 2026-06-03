"""REPL/TUI auto-push parity (v0.6.0 cross-surface gap closure).

The v0.6.0 ``_maybe_auto_push`` helper is wired into the tail of
``urika run`` / ``urika finalize`` / ``urika build-tool`` so that the
project gets backed up after each event when ``[github].auto_push =
true`` and the event is listed in ``[github].auto_push_after``.

For ``/run`` and ``/finalize`` the REPL handlers delegate to the same
Click commands via ``Context.invoke``, so the hook fires "for free".
``/build-tool`` historically went straight to ``_run_single_agent``,
skipping the CLI altogether — so the auto-push hook never fired from
the REPL/TUI. This test pins the fix.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace
from urika.repl.cmd_agents import cmd_build_tool
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


def test_cmd_build_tool_calls_maybe_auto_push_on_success(tmp_path, monkeypatch) -> None:
    """A successful /build-tool must invoke ``_maybe_auto_push`` with
    ``event="build-tool"``. Pre-fix the REPL handler went straight to
    ``_run_single_agent`` and the auto-push hook never fired."""
    session = _setup(tmp_path, monkeypatch)

    # Stub the heavy agent runner — return non-empty text so the
    # post-success branch executes.
    monkeypatch.setattr(
        "urika.repl.cmd_agents._run_single_agent",
        lambda *a, **kw: "Built a tool.\n",
    )

    with patch("urika.cli.github._maybe_auto_push") as spy:
        cmd_build_tool(session, "build a paired-t-test helper")

    assert spy.called, (
        "/build-tool must invoke _maybe_auto_push so projects with "
        "[github] auto_push = true get backed up after a successful "
        "tool build — same parity as the CLI ``urika build-tool``."
    )
    # Pin the event tag — the auto_push_after list filters by this.
    args, kwargs = spy.call_args
    event = kwargs.get("event") or (args[1] if len(args) > 1 else None)
    assert event == "build-tool"


def test_cmd_build_tool_does_not_call_auto_push_on_empty_output(
    tmp_path, monkeypatch
) -> None:
    """When the agent returns an empty string (failure/no-op), don't
    auto-push — matches the CLI which only auto-pushes after
    ``result.success and result.text_output``."""
    session = _setup(tmp_path, monkeypatch)

    monkeypatch.setattr(
        "urika.repl.cmd_agents._run_single_agent",
        lambda *a, **kw: "",
    )

    with patch("urika.cli.github._maybe_auto_push") as spy:
        cmd_build_tool(session, "build something")

    assert not spy.called, "Empty agent output means failure — auto-push must not fire."
