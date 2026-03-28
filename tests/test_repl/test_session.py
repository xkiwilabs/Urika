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

    # ── Agent state ──────────────────────────────────────────────

    def test_agent_not_running_by_default(self) -> None:
        session = ReplSession()
        assert session.agent_running is False
        assert session.agent_name == ""
        assert session.agent_activity == ""

    def test_set_agent_running(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent", activity="Running\u2026")
        assert session.agent_running is True
        assert session.agent_name == "task_agent"
        assert session.agent_activity == "Running\u2026"

    def test_set_agent_idle(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        session.set_agent_idle()
        assert session.agent_running is False
        assert session.agent_name == ""
        assert session.agent_activity == ""

    def test_set_agent_idle_with_error(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        session.set_agent_idle(error="something went wrong")
        assert session.agent_running is False
        assert session.agent_error == "something went wrong"

    def test_update_agent_activity(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        session.update_agent_activity(
            activity="Evaluating\u2026", turn="Turn 3/5", model="claude-3"
        )
        assert session.agent_activity == "Evaluating\u2026"
        assert session.agent_turn == "Turn 3/5"
        assert session.model == "claude-3"

    def test_update_agent_activity_partial(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent", activity="Working\u2026")
        session.update_agent_activity(model="claude-3")
        # Activity should remain unchanged since we passed empty string
        assert session.agent_activity == "Working\u2026"
        assert session.model == "claude-3"

    def test_set_agent_running_defaults_activity(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        assert session.agent_activity == "Working\u2026"

    # ── Notification bus ──────────────────────────────────────

    def test_notification_bus_default_none(self) -> None:
        session = ReplSession()
        assert session.notification_bus is None

    # ── Agent active (command-level tracking) ─────────────────

    def test_agent_active_default_false(self) -> None:
        session = ReplSession()
        assert session.agent_active is False
        assert session.active_command == ""

    def test_set_agent_active(self) -> None:
        session = ReplSession()
        session.set_agent_active("run")
        assert session.agent_active is True
        assert session.active_command == "run"

    def test_set_agent_idle_clears_active(self) -> None:
        session = ReplSession()
        session.set_agent_active("run")
        session.set_agent_idle()
        assert session.agent_active is False
        assert session.active_command == ""

    # ── Remote command queue ──────────────────────────────────

    def test_remote_command_queue_empty(self) -> None:
        session = ReplSession()
        assert session.has_remote_command is False
        assert session.pop_remote_command() is None

    def test_queue_remote_command(self) -> None:
        session = ReplSession()
        session.queue_remote_command("run", "experiment-1")
        assert session.has_remote_command is True
        cmd = session.pop_remote_command()
        assert cmd == ("run", "experiment-1")

    def test_queue_multiple_remote_commands(self) -> None:
        session = ReplSession()
        session.queue_remote_command("run", "exp-1")
        session.queue_remote_command("status", "")
        first = session.pop_remote_command()
        assert first == ("run", "exp-1")
        second = session.pop_remote_command()
        assert second == ("status", "")
        assert session.has_remote_command is False

    def test_clear_remote_queue(self) -> None:
        session = ReplSession()
        session.queue_remote_command("run", "exp-1")
        session.queue_remote_command("status", "")
        session.clear_remote_queue()
        assert session.has_remote_command is False

    def test_load_project_clears_remote_queue(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.queue_remote_command("run", "exp-1")
        session.load_project(tmp_path, "new-project")
        assert session.has_remote_command is False
        assert session.agent_active is False
        assert session.active_command == ""
