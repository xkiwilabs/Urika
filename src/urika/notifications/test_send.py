"""Reusable helper for sending a synthetic 'test' notification through a bus.

This module provides a non-printing entry point for triggering test
notifications across every channel attached to a :class:`NotificationBus`.
It returns structured per-channel results so callers (CLI, dashboard) can
render outcomes however they like.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from urika.notifications.events import NotificationEvent

if TYPE_CHECKING:
    from urika.notifications.bus import NotificationBus


def send_test_through_bus(
    bus: NotificationBus, project_name: str = "test"
) -> dict[str, dict[str, str]]:
    """Send a synthetic 'test' notification through every channel on *bus*.

    Calls ``health_check()`` on each channel first. If the probe fails, the
    result entry is ``{"status": "error", "message": "health check failed: ..."}``
    and ``send()`` is NOT invoked — so callers (dashboard, CLI) see the actual
    auth/config error instead of a silent swallow inside ``send()``.

    Returns a dict keyed by a stable per-channel name (class name + index for
    duplicates) where each value is ``{"status": "ok" | "error", "message": str}``.
    """
    event = NotificationEvent(
        event_type="test",
        project_name=project_name,
        summary="Test notification from Urika",
        priority="medium",
    )
    results: dict[str, dict[str, str]] = {}
    seen: dict[str, int] = {}
    for ch in bus.channels:
        cls = type(ch).__name__
        idx = seen.get(cls, 0)
        seen[cls] = idx + 1
        key = cls if idx == 0 else f"{cls}_{idx}"

        # Probe credentials/config before send so we surface the real error
        # rather than the listener-thread-swallow path inside send().
        try:
            ok, msg = ch.health_check()
        except Exception as exc:
            ok, msg = False, str(exc)
        if not ok:
            results[key] = {
                "status": "error",
                "message": f"health check failed: {msg}",
            }
            continue

        try:
            ch.send(event)
            results[key] = {"status": "ok", "message": ""}
        except Exception as exc:
            results[key] = {"status": "error", "message": str(exc)}
    return results
