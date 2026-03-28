"""Tests for the NotificationBus dispatcher."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from urika.notifications.base import NotificationChannel
from urika.notifications.bus import NotificationBus
from urika.notifications.events import NotificationEvent


class FakeChannel(NotificationChannel):
    """Test double that records all sent events."""

    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def send(self, event: NotificationEvent) -> None:
        self.events.append(event)


class ErrorChannel(NotificationChannel):
    """Test double that raises on every send."""

    def send(self, event: NotificationEvent) -> None:
        raise RuntimeError("boom")


def _make_event(summary: str = "test", priority: str = "medium") -> NotificationEvent:
    return NotificationEvent(
        event_type="test_event",
        project_name="proj",
        summary=summary,
        priority=priority,
    )


class TestNotificationBus:
    def test_add_channel(self):
        """add_channel returns self (chaining), channel in list."""
        bus = NotificationBus()
        fake = FakeChannel()
        result = bus.add_channel(fake)
        assert result is bus
        assert fake in bus.channels

    def test_start_stop(self):
        """start() creates thread, stop() joins it."""
        bus = NotificationBus()
        bus.add_channel(FakeChannel())
        bus.start()
        assert bus._thread is not None
        assert bus._thread.is_alive()
        bus.stop()
        assert bus._thread is None

    def test_dispatch_to_channel(self):
        """Events dispatched to a single channel."""
        bus = NotificationBus()
        fake = FakeChannel()
        bus.add_channel(fake)
        bus.start()
        try:
            bus.notify(_make_event("hello"))
            time.sleep(0.5)
            assert len(fake.events) == 1
            assert fake.events[0].summary == "hello"
        finally:
            bus.stop()

    def test_dispatch_multiple_channels(self):
        """Two channels both receive the event."""
        bus = NotificationBus()
        fake1 = FakeChannel()
        fake2 = FakeChannel()
        bus.add_channel(fake1)
        bus.add_channel(fake2)
        bus.start()
        try:
            bus.notify(_make_event("multi"))
            time.sleep(0.5)
            assert len(fake1.events) == 1
            assert len(fake2.events) == 1
            assert fake1.events[0].summary == "multi"
        finally:
            bus.stop()

    def test_channel_error_doesnt_crash(self, caplog):
        """Channel that raises in send() -- bus logs but doesn't crash."""
        bus = NotificationBus()
        error_ch = ErrorChannel()
        fake = FakeChannel()
        bus.add_channel(error_ch)
        bus.add_channel(fake)
        bus.start()
        try:
            with caplog.at_level(logging.WARNING, logger="urika.notifications.bus"):
                bus.notify(_make_event("survives"))
                time.sleep(0.5)
            # The healthy channel still received the event
            assert len(fake.events) == 1
            assert fake.events[0].summary == "survives"
            assert "Notification send failed" in caplog.text
        finally:
            bus.stop()

    def test_on_progress_turn(self):
        """on_progress('turn', ...) creates a turn_started event."""
        bus = NotificationBus(project_name="proj")
        fake = FakeChannel()
        bus.add_channel(fake)
        bus.start()
        try:
            bus.on_progress("turn", "Turn 1/5")
            time.sleep(0.5)
            assert len(fake.events) == 1
            assert fake.events[0].event_type == "turn_started"
            assert fake.events[0].summary == "Turn 1/5"
            assert fake.events[0].priority == "low"
        finally:
            bus.stop()

    def test_on_progress_criteria_met(self):
        """on_progress('result', 'Criteria met!') creates a high-priority event."""
        bus = NotificationBus(project_name="proj")
        fake = FakeChannel()
        bus.add_channel(fake)
        bus.start()
        try:
            bus.on_progress("result", "Criteria met! r2=0.95")
            time.sleep(0.5)
            assert len(fake.events) == 1
            assert fake.events[0].event_type == "criteria_met"
            assert fake.events[0].priority == "high"
        finally:
            bus.stop()

    def test_on_progress_skips_agent_events(self):
        """on_progress('agent', ...) returns None (no notification)."""
        bus = NotificationBus(project_name="proj")
        fake = FakeChannel()
        bus.add_channel(fake)
        bus.start()
        try:
            bus.on_progress("agent", "Task agent - running analysis")
            time.sleep(0.5)
            assert len(fake.events) == 0
        finally:
            bus.stop()

    def test_set_experiment(self):
        """set_experiment updates the context for subsequent events."""
        bus = NotificationBus(project_name="proj")
        fake = FakeChannel()
        bus.add_channel(fake)
        bus.start()
        try:
            bus.set_experiment("exp-001")
            bus.on_progress("turn", "Turn 1/3")
            time.sleep(0.5)
            assert len(fake.events) == 1
            assert fake.events[0].experiment_id == "exp-001"
        finally:
            bus.stop()

    def test_stop_drains_queue(self):
        """Events queued before stop() are dispatched before thread exits."""
        bus = NotificationBus()
        fake = FakeChannel()
        bus.add_channel(fake)
        bus.start()
        # Queue several events without waiting
        for i in range(5):
            bus.notify(_make_event(f"drain-{i}"))
        bus.stop()
        # All events should have been delivered
        assert len(fake.events) == 5
        summaries = [e.summary for e in fake.events]
        for i in range(5):
            assert f"drain-{i}" in summaries


class TestClassifyRemoteCommand:
    def test_read_only(self):
        from urika.notifications.bus import classify_remote_command

        assert classify_remote_command("status") == "read_only"
        assert classify_remote_command("results") == "read_only"
        assert classify_remote_command("methods") == "read_only"
        assert classify_remote_command("help") == "read_only"

    def test_run_control(self):
        from urika.notifications.bus import classify_remote_command

        assert classify_remote_command("pause") == "run_control"
        assert classify_remote_command("stop") == "run_control"
        assert classify_remote_command("resume") == "run_control"

    def test_agent(self):
        from urika.notifications.bus import classify_remote_command

        assert classify_remote_command("run") == "agent"
        assert classify_remote_command("advisor") == "agent"
        assert classify_remote_command("evaluate") == "agent"
        assert classify_remote_command("finalize") == "agent"

    def test_rejected(self):
        from urika.notifications.bus import classify_remote_command

        assert classify_remote_command("config") == "rejected"
        assert classify_remote_command("new") == "rejected"
        assert classify_remote_command("quit") == "rejected"

    def test_strips_slash_and_whitespace(self):
        from urika.notifications.bus import classify_remote_command

        assert classify_remote_command("/status") == "read_only"
        assert classify_remote_command("  pause  ") == "run_control"
        assert classify_remote_command("/run") == "agent"


class TestHandleRemoteCommand:
    """Tests for the handle_remote_command method on NotificationBus."""

    def test_rejected_command(self):
        bus = NotificationBus()
        responses = []
        bus.handle_remote_command("config", respond=responses.append)
        assert len(responses) == 1
        assert "not available remotely" in responses[0]

    def test_read_only_no_project(self):
        bus = NotificationBus()
        responses = []
        bus.handle_remote_command("status", respond=responses.append)
        assert responses == ["No project loaded."]

    def test_read_only_help(self):
        bus = NotificationBus(project_path=Path("/tmp/fake"))
        responses = []
        bus.handle_remote_command("help", respond=responses.append)
        assert len(responses) == 1
        assert "/status" in responses[0]
        assert "/pause" in responses[0]
        assert "/run" in responses[0]

    def test_run_control_pause_no_session(self):
        bus = NotificationBus()
        responses = []
        bus.handle_remote_command("pause", respond=responses.append)
        assert "No active run" in responses[0]

    def test_run_control_pause_with_active_session(self):
        bus = NotificationBus()

        class FakeController:
            paused = False

            def request_pause(self):
                self.paused = True

        class FakeSession:
            agent_active = True

        bus._controller = FakeController()
        bus._session = FakeSession()
        responses = []
        bus.handle_remote_command("pause", respond=responses.append)
        assert bus._controller.paused
        assert "Pause requested" in responses[0]

    def test_run_control_stop_clears_queue(self):
        bus = NotificationBus()

        class FakeController:
            stopped = False

            def request_stop(self):
                self.stopped = True

        class FakeSession:
            agent_active = True
            cleared = False

            def clear_remote_queue(self):
                self.cleared = True

        bus._controller = FakeController()
        bus._session = FakeSession()
        responses = []
        bus.handle_remote_command("stop", respond=responses.append)
        assert bus._controller.stopped
        assert bus._session.cleared
        assert "Stopped" in responses[0]

    def test_agent_no_session(self):
        bus = NotificationBus()
        responses = []
        bus.handle_remote_command("run", respond=responses.append)
        assert "No active REPL session" in responses[0]

    def test_agent_queued_while_busy(self):
        bus = NotificationBus()

        class FakeSession:
            agent_active = True
            active_command = "evaluate"
            queued = []

            def queue_remote_command(self, cmd, args):
                self.queued.append((cmd, args))

        bus._session = FakeSession()
        responses = []
        bus.handle_remote_command("advisor", args="try PCA?", respond=responses.append)
        assert len(bus._session.queued) == 1
        assert bus._session.queued[0] == ("advisor", "try PCA?")
        assert "queued" in responses[0]
        assert "evaluate" in responses[0]

    def test_agent_run_blocked_during_run(self):
        bus = NotificationBus()

        class FakeSession:
            agent_active = True
            active_command = "run"
            queued = []

            def queue_remote_command(self, cmd, args):
                self.queued.append((cmd, args))

        bus._session = FakeSession()
        responses = []
        bus.handle_remote_command("run", respond=responses.append)
        assert len(bus._session.queued) == 0
        assert "Run in progress" in responses[0]

    def test_agent_queued_when_idle(self):
        bus = NotificationBus()

        class FakeSession:
            agent_active = False
            active_command = ""
            queued = []

            def queue_remote_command(self, cmd, args):
                self.queued.append((cmd, args))

        bus._session = FakeSession()
        responses = []
        bus.handle_remote_command("plan", respond=responses.append)
        assert bus._session.queued == [("plan", "")]
        assert "/plan queued." in responses[0]

    def test_resume_when_idle(self):
        bus = NotificationBus()

        class FakeSession:
            agent_active = False
            queued = []

            def queue_remote_command(self, cmd, args):
                self.queued.append((cmd, args))

        bus._session = FakeSession()
        responses = []
        bus.handle_remote_command("resume", respond=responses.append)
        assert ("run", "--resume") in bus._session.queued
        assert "Resume queued" in responses[0]

    def test_no_respond_callable(self):
        """handle_remote_command works even if respond is None."""
        bus = NotificationBus()
        # Should not raise
        bus.handle_remote_command("config")
