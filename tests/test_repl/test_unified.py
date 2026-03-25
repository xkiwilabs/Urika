"""Tests for REPL input queuing (Phase B preparation)."""

from __future__ import annotations

from urika.repl_session import ReplSession


class TestInputQueueing:
    """Tests that input queuing works for future Phase B."""

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
