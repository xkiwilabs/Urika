"""NotificationBus — fan-out dispatcher for notification events."""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urika.notifications.base import NotificationChannel
    from urika.orchestrator.pause import PauseController

from urika.notifications.events import NotificationEvent

logger = logging.getLogger(__name__)


class NotificationBus:
    """Dispatches notification events to configured channels via a background thread."""

    def __init__(self, project_name: str = "") -> None:
        self.project_name = project_name
        self.channels: list[NotificationChannel] = []
        self._queue: queue.Queue[NotificationEvent | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._experiment_id = ""
        self._turn = ""

    def add_channel(self, channel: NotificationChannel) -> NotificationBus:
        """Add a channel. Returns self for chaining."""
        self.channels.append(channel)
        return self

    def start(self, controller: PauseController | None = None) -> None:
        """Start the dispatch thread and channel listeners."""
        self._thread = threading.Thread(
            target=self._dispatch_loop, name="urika-notifications", daemon=True
        )
        self._thread.start()
        for ch in self.channels:
            try:
                if controller is not None:
                    ch.start_listener(controller)
            except Exception as exc:
                logger.warning(
                    "Failed to start listener for %s: %s", type(ch).__name__, exc
                )

    def stop(self) -> None:
        """Stop dispatch thread and all listeners. Drains remaining events."""
        self._queue.put(None)  # Sentinel to stop dispatch loop
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        for ch in self.channels:
            try:
                ch.stop_listener()
            except Exception as exc:
                logger.warning(
                    "Failed to stop listener for %s: %s", type(ch).__name__, exc
                )

    def notify(self, event: NotificationEvent) -> None:
        """Enqueue an event for background dispatch. Non-blocking."""
        self._queue.put(event)

    def on_progress(self, event: str, detail: str = "") -> None:
        """Adapter: convert on_progress callbacks to NotificationEvents.

        Maps orchestrator events to notification events with appropriate
        priority levels. Not all progress events generate notifications.
        """
        if event == "turn":
            self._turn = detail

        notification = self._map_progress_event(event, detail)
        if notification is not None:
            self.notify(notification)

    def set_experiment(self, experiment_id: str) -> None:
        """Update the current experiment ID for context in notifications."""
        self._experiment_id = experiment_id

    def _map_progress_event(self, event: str, detail: str) -> NotificationEvent | None:
        """Map an on_progress event to a NotificationEvent, or None to skip."""
        if event == "turn":
            return NotificationEvent(
                event_type="turn_started",
                project_name=self.project_name,
                experiment_id=self._experiment_id,
                summary=detail,
                priority="low",
            )
        if event == "result" and "Criteria met" in detail:
            return NotificationEvent(
                event_type="criteria_met",
                project_name=self.project_name,
                experiment_id=self._experiment_id,
                summary=detail,
                priority="high",
            )
        if event == "result" and "Recorded" in detail:
            return NotificationEvent(
                event_type="run_recorded",
                project_name=self.project_name,
                experiment_id=self._experiment_id,
                summary=f"{self._turn} — {detail}",
                details={"turn": self._turn},
                priority="low",
            )
        if event == "phase" and "Paused" in detail:
            return NotificationEvent(
                event_type="paused",
                project_name=self.project_name,
                experiment_id=self._experiment_id,
                summary=detail,
                priority="medium",
            )
        if (
            event == "agent"
            and "Advisor" in detail
            and "proposing next experiment" in detail
        ):
            return NotificationEvent(
                event_type="experiment_starting",
                project_name=self.project_name,
                summary=detail,
                priority="low",
            )
        return None

    def _dispatch_loop(self) -> None:
        """Background thread: read events from queue and send to all channels."""
        while True:
            try:
                event = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if event is None:
                while not self._queue.empty():
                    try:
                        remaining = self._queue.get_nowait()
                        if remaining is not None:
                            self._send_to_all(remaining)
                    except queue.Empty:
                        break
                break
            self._send_to_all(event)

    def _send_to_all(self, event: NotificationEvent) -> None:
        """Send event to all channels. Errors are logged, never raised."""
        for ch in self.channels:
            try:
                ch.send(event)
            except Exception as exc:
                logger.warning(
                    "Notification send failed for %s: %s", type(ch).__name__, exc
                )
