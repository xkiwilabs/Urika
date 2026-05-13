"""``/resume-session`` cross-session restore.

The existing tab-completion tests pin the suggester behavior; this
file covers the actual *restore*: when the user picks a saved session
by number, its ``recent_messages`` reach the orchestrator's
conversation history, ``session._orch_session`` is set, and the user
gets a confirmation. Pre-this-file the load → orchestrator handoff
was completely untested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl.commands_session import cmd_resume_session
from urika.repl.session import ReplSession


def _setup_with_sessions(tmp_path: Path, n_sessions: int = 2) -> tuple[ReplSession, list]:
    from urika.core.models import ProjectConfig
    from urika.core.orchestrator_sessions import save_session, OrchestratorSession
    from urika.core.workspace import create_project_workspace
    from datetime import datetime, timezone

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    saved = []
    for i in range(n_sessions):
        sess = OrchestratorSession(
            session_id=f"sess-{i}",
            started=datetime.now(timezone.utc).isoformat(),
            updated=datetime.now(timezone.utc).isoformat(),
            recent_messages=[
                {"role": "user", "content": f"hi from sess-{i}"},
                {"role": "assistant", "content": f"response from sess-{i}"},
            ],
            preview=f"Preview {i}",
        )
        save_session(proj, sess)
        saved.append(sess)
    session = ReplSession()
    session.load_project(path=proj, name="alpha")
    return session, saved


class _StubOrchestrator:
    """Records calls to set_messages, mirrors OrchestratorChat's
    contract for the tests."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def set_messages(self, msgs):  # noqa: ANN001
        self.messages = list(msgs)


def test_no_sessions_explains_empty_state(tmp_path: Path, capsys) -> None:
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "p"
    create_project_workspace(
        proj, ProjectConfig(name="p", question="Q?", mode="exploratory")
    )
    session = ReplSession()
    session.load_project(path=proj, name="p")
    cmd_resume_session(session, "")
    out = capsys.readouterr().out
    assert "No saved sessions" in out


def test_no_args_lists_recent_sessions(tmp_path: Path, capsys) -> None:
    session, _ = _setup_with_sessions(tmp_path, n_sessions=2)
    cmd_resume_session(session, "")
    out = capsys.readouterr().out
    assert "Recent sessions" in out
    assert "/resume-session <number>" in out


def test_invalid_number_string_explains_error(tmp_path: Path, capsys) -> None:
    session, _ = _setup_with_sessions(tmp_path)
    cmd_resume_session(session, "notanumber")
    out = capsys.readouterr().out
    assert "Invalid number" in out


def test_out_of_range_number_explains_error(tmp_path: Path, capsys) -> None:
    session, _ = _setup_with_sessions(tmp_path, n_sessions=1)
    cmd_resume_session(session, "99")
    out = capsys.readouterr().out
    assert "Invalid session number" in out


def test_valid_number_restores_to_orchestrator(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """The load → orchestrator handoff: set_messages called with the
    saved session's recent_messages, session._orch_session populated,
    user notified."""
    session, saved = _setup_with_sessions(tmp_path, n_sessions=2)
    stub_orch = _StubOrchestrator()
    monkeypatch.setattr(
        "urika.repl.main._get_orchestrator", lambda _s: stub_orch
    )
    cmd_resume_session(session, "1")
    # Most recent (top of the list — sessions are sorted by updated desc).
    # set_messages received SOME saved session's messages.
    assert stub_orch.messages
    assert any("hi from sess" in m["content"] for m in stub_orch.messages)
    assert any("response from sess" in m["content"] for m in stub_orch.messages)
    # The session ref was attached for downstream `/save` etc.
    assert getattr(session, "_orch_session", None) is not None
    out = capsys.readouterr().out
    assert "Resumed session" in out
    # Turn count reported.
    assert "1 turns" in out or "turn" in out
