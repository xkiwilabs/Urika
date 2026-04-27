"""Tests for send_test_through_bus reusable helper."""

from unittest.mock import MagicMock

from urika.notifications.base import NotificationChannel
from urika.notifications.bus import NotificationBus
from urika.notifications.test_send import send_test_through_bus


def test_send_test_returns_per_channel_status():
    bus = NotificationBus(project_name="p")
    fake_ok = MagicMock(spec=NotificationChannel)
    fake_fail = MagicMock(spec=NotificationChannel)
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
