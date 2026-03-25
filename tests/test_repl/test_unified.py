"""Tests for the unified three-zone REPL interface."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit.formatted_text import ANSI

from urika.repl import (
    _BACKGROUND_COMMANDS,
    _toolbar_agent_running,
    _toolbar_idle,
)
from urika.repl_session import ReplSession


class TestToolbarIdle:
    """Tests for the idle toolbar renderer."""

    def test_returns_ansi_type(self) -> None:
        session = ReplSession()
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        assert isinstance(result, ANSI)

    def test_contains_urika_brand(self) -> None:
        session = ReplSession()
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        # ANSI objects store their raw value
        raw = result.value
        assert "urika" in raw

    def test_shows_project_name(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "my-study")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        raw = result.value
        assert "my-study" in raw

    def test_shows_privacy_mode(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "my-study")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "private")
        raw = result.value
        assert "private" in raw

    def test_hides_open_privacy(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "my-study")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        raw = result.value
        # Should NOT contain "open" as a privacy label
        # (but "urika" contains no substring "open", so just check
        # that there's no " open" pattern after the project name)
        assert "\u00b7 open" not in raw

    def test_shows_model(self) -> None:
        session = ReplSession()
        session.model = "claude-3"
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        raw = result.value
        assert "claude-3" in raw

    def test_shows_token_count(self) -> None:
        session = ReplSession()
        session.record_agent_call(tokens_in=5000, tokens_out=1000, cost_usd=0.10)
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        raw = result.value
        assert "6K" in raw
        assert "$0.10" in raw

    def test_no_tokens_when_no_calls(self) -> None:
        session = ReplSession()
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_idle(session, sep, lambda p: "open")
        raw = result.value
        assert "tokens" not in raw


class TestToolbarAgentRunning:
    """Tests for the agent-running toolbar renderer."""

    def test_returns_ansi_type(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent", activity="Running\u2026")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_agent_running(session, sep)
        assert isinstance(result, ANSI)

    def test_shows_agent_label(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent", activity="Running\u2026")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_agent_running(session, sep)
        raw = result.value
        assert "Task Agent" in raw

    def test_shows_activity(self) -> None:
        session = ReplSession()
        session.set_agent_running(
            agent_name="planning_agent", activity="Designing method\u2026"
        )
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_agent_running(session, sep)
        raw = result.value
        assert "Designing method" in raw

    def test_shows_turn_info(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "test-proj")
        session.set_agent_running(agent_name="task_agent", activity="Running\u2026")
        session.update_agent_activity(turn="Turn 3/5")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_agent_running(session, sep)
        raw = result.value
        assert "Turn 3/5" in raw

    def test_shows_model_on_line2(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent", activity="Running\u2026")
        session.model = "claude-3"
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_agent_running(session, sep)
        raw = result.value
        assert "claude-3" in raw

    def test_shows_project_name(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "dht-study")
        session.set_agent_running(agent_name="task_agent")
        sep = "\033[2m" + "\u2500" * 40 + "\033[0m"
        result = _toolbar_agent_running(session, sep)
        raw = result.value
        assert "dht-study" in raw


class TestBackgroundCommands:
    """Tests for the background command set."""

    def test_background_commands_disabled_for_phase_a(self) -> None:
        # Background commands disabled in Phase A to avoid
        # prompt conflicts with interactive settings dialogs.
        # Will be re-enabled in Phase B (Textual).
        assert len(_BACKGROUND_COMMANDS) == 0

    def test_help_is_not_background(self) -> None:
        assert "help" not in _BACKGROUND_COMMANDS

    def test_list_is_not_background(self) -> None:
        assert "list" not in _BACKGROUND_COMMANDS


class TestInputQueueing:
    """Tests that input queuing works when agent is running."""

    def test_queue_input_during_agent_run(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        session.queue_input("try random forest next")
        assert session.has_queued_input is True
        text = session.pop_queued_input()
        assert text == "try random forest next"

    def test_multiple_queued_inputs(self) -> None:
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        session.queue_input("instruction 1")
        session.queue_input("instruction 2")
        text = session.pop_queued_input()
        assert "instruction 1" in text
        assert "instruction 2" in text
