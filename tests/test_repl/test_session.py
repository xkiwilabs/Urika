"""Tests for REPL session state."""

from __future__ import annotations
from pathlib import Path
from urika.repl_session import ReplSession


class TestReplSession:
    def test_initial_state(self) -> None:
        session = ReplSession()
        assert session.project_path is None
        assert session.project_name is None
        assert session.conversation == []

    def test_load_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "my-project")
        assert session.project_path == tmp_path
        assert session.project_name == "my-project"

    def test_clear_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "proj")
        session.clear_project()
        assert session.project_path is None

    def test_add_conversation(self) -> None:
        session = ReplSession()
        session.add_message("user", "try LSTM")
        session.add_message("advisor", "LSTM could work...")
        assert len(session.conversation) == 2

    def test_conversation_context_limited(self) -> None:
        session = ReplSession()
        for i in range(20):
            session.add_message("user", f"msg {i}")
        context = session.get_conversation_context()
        assert "msg 19" in context
        assert "msg 0" not in context

    def test_has_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        assert not session.has_project
        session.load_project(tmp_path, "proj")
        assert session.has_project

    def test_input_queue_empty_by_default(self) -> None:
        session = ReplSession()
        assert session.has_queued_input is False
        assert session.pop_queued_input() == ""

    def test_input_queue_stores_and_retrieves(self) -> None:
        session = ReplSession()
        session.queue_input("try random forest")
        assert session.has_queued_input is True
        text = session.pop_queued_input()
        assert text == "try random forest"
        assert session.has_queued_input is False

    def test_input_queue_concatenates_multiple(self) -> None:
        session = ReplSession()
        session.queue_input("first instruction")
        session.queue_input("second instruction")
        text = session.pop_queued_input()
        assert "first instruction" in text
        assert "second instruction" in text

    def test_input_queue_ignores_whitespace(self) -> None:
        session = ReplSession()
        session.queue_input("  ")
        session.queue_input("")
        assert session.has_queued_input is False
