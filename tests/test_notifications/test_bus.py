"""Tests for the NotificationBus dispatcher."""

from __future__ import annotations

import logging
import time

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
