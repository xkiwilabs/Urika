"""Tests for send_test_through_bus reusable helper."""

from unittest.mock import MagicMock

from urika.notifications.base import NotificationChannel
from urika.notifications.bus import NotificationBus
from urika.notifications.test_send import send_test_through_bus


def test_send_test_returns_per_channel_status():
    bus = NotificationBus(project_name="p")
    fake_ok = MagicMock(spec=NotificationChannel)
    fake_ok.health_check.return_value = (True, "")
    fake_fail = MagicMock(spec=NotificationChannel)
    fake_fail.health_check.return_value = (True, "")
    fake_fail.send.side_effect = RuntimeError("bad token")
    bus.add_channel(fake_ok)
    bus.add_channel(fake_fail)

    results = send_test_through_bus(bus)
    # Two channels of class MagicMock — keys are MagicMock, MagicMock_1
    assert len(results) == 2
    statuses = {r["status"] for r in results.values()}
    assert statuses == {"ok", "error"}
    error_messages = [r["message"] for r in results.values() if r["status"] == "error"]
    assert any("bad token" in m for m in error_messages)


def test_send_test_reports_health_check_failure():
    """Health check failure short-circuits send and surfaces the error."""
    bus = NotificationBus(project_name="p")
    ch = MagicMock(spec=NotificationChannel)
    ch.health_check.return_value = (False, "invalid token")
    bus.add_channel(ch)

    results = send_test_through_bus(bus)
    assert len(results) == 1
    result = next(iter(results.values()))
    assert result["status"] == "error"
    assert "invalid token" in result["message"]
    # send was NOT called because health check failed first
    ch.send.assert_not_called()


def test_send_test_handles_health_check_raising():
    """A health_check() that raises is treated as unhealthy, not propagated."""
    bus = NotificationBus(project_name="p")
    ch = MagicMock(spec=NotificationChannel)
    ch.health_check.side_effect = RuntimeError("network blew up")
    bus.add_channel(ch)

    results = send_test_through_bus(bus)
    assert len(results) == 1
    result = next(iter(results.values()))
    assert result["status"] == "error"
    assert "network blew up" in result["message"]
    ch.send.assert_not_called()


def test_send_test_empty_bus_returns_empty_dict():
    bus = NotificationBus(project_name="p")
    assert send_test_through_bus(bus) == {}


def test_send_test_uses_test_event_type():
    bus = NotificationBus(project_name="p")
    captured: list = []

    class CapturingChannel(NotificationChannel):
        def send(self, event):
            captured.append(event)

        def start_listener(self, *args, **kwargs):
            pass

        def stop_listener(self):
            pass

    bus.add_channel(CapturingChannel())
    send_test_through_bus(bus, project_name="myproj")
    assert len(captured) == 1
    assert captured[0].event_type == "test"
    assert captured[0].project_name == "myproj"
