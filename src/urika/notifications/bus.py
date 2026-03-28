"""NotificationBus — fan-out dispatcher for notification events."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urika.notifications.base import NotificationChannel
    from urika.orchestrator.pause import PauseController

from urika.notifications.events import NotificationEvent

logger = logging.getLogger(__name__)

_READ_ONLY_COMMANDS = frozenset(
    {"status", "results", "methods", "criteria", "experiments", "logs", "usage", "help"}
)
_RUN_CONTROL_COMMANDS = frozenset({"pause", "stop", "resume"})
_AGENT_COMMANDS = frozenset(
    {
        "run",
        "advisor",
        "evaluate",
        "plan",
        "report",
        "present",
        "finalize",
        "build-tool",
    }
)


def classify_remote_command(command: str) -> str:
    """Classify a remote command: read_only, run_control, agent, or rejected."""
    cmd = command.lower().strip().replace("/", "")
    if cmd in _READ_ONLY_COMMANDS:
        return "read_only"
    if cmd in _RUN_CONTROL_COMMANDS:
        return "run_control"
    if cmd in _AGENT_COMMANDS:
        return "agent"
    return "rejected"


class NotificationBus:
    """Dispatches notification events to configured channels via a background thread."""

    def __init__(
        self, project_name: str = "", project_path: Path | None = None
    ) -> None:
        self.project_name = project_name
        self._project_path = project_path
        self.channels: list[NotificationChannel] = []
        self._queue: queue.Queue[NotificationEvent | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._experiment_id = ""
        self._turn = ""
        self._controller: PauseController | None = None
        self._session: object = None  # ReplSession (avoid circular import)

    def add_channel(self, channel: NotificationChannel) -> NotificationBus:
        """Add a channel. Returns self for chaining."""
        self.channels.append(channel)
        return self

    def start(
        self,
        controller: PauseController | None = None,
        session: object = None,
    ) -> None:
        """Start the dispatch thread and channel listeners."""
        self._controller = controller
        self._session = session
        self._thread = threading.Thread(
            target=self._dispatch_loop, name="urika-notifications", daemon=True
        )
        self._thread.start()
        for ch in self.channels:
            try:
                if controller is not None:
                    ch.start_listener(
                        controller, project_path=self._project_path, bus=self
                    )
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

    # ------------------------------------------------------------------
    # Remote command handling
    # ------------------------------------------------------------------

    def handle_remote_command(
        self, command: str, args: str = "", respond: object = None
    ) -> None:
        """Handle an inbound command from Telegram/Slack.

        Args:
            command: the command name (e.g. "status", "run", "pause")
            args: command arguments (e.g. "what should I try next?")
            respond: callable(text) to send response back to the channel
        """
        _respond = respond or (lambda t: None)
        category = classify_remote_command(command)

        if category == "rejected":
            _respond(f"/{command} is not available remotely. Use the terminal.")
            return

        if category == "read_only":
            text = self._execute_read_only(command, args)
            _respond(text)
            return

        if category == "run_control":
            self._execute_run_control(command, _respond)
            return

        if category == "agent":
            self._queue_agent_command(command, args, _respond)
            return

    def _execute_read_only(self, command: str, args: str) -> str:
        """Execute a read-only query and return the text result."""
        if self._project_path is None:
            return "No project loaded."

        from urika.notifications.queries import (
            get_criteria_text,
            get_experiments_text,
            get_logs_text,
            get_methods_text,
            get_results_text,
            get_status_text,
            get_usage_text,
        )

        cmd = command.lower().strip()
        if cmd == "status":
            return get_status_text(self._project_path)
        if cmd == "results":
            return get_results_text(self._project_path)
        if cmd == "methods":
            return get_methods_text(self._project_path)
        if cmd == "criteria":
            return get_criteria_text(self._project_path)
        if cmd == "experiments":
            return get_experiments_text(self._project_path)
        if cmd == "usage":
            return get_usage_text(self._project_path)
        if cmd == "logs":
            return get_logs_text(self._project_path, args.strip())
        if cmd == "help":
            return (
                "Available commands:\n"
                "  /status /results /methods /criteria /experiments /logs /usage\n"
                "  /pause /stop /resume\n"
                "  /run /advisor <question> /evaluate /plan /report"
                " /present /finalize /build-tool <text>"
            )
        return f"Unknown command: /{command}"

    def _execute_run_control(self, command: str, respond) -> None:
        """Execute a run control command."""
        if command == "pause":
            if self._controller and self._session and self._session.agent_active:
                self._controller.request_pause()
                respond("Pause requested \u23f8")
            else:
                respond("No active run to pause.")
        elif command == "stop":
            if self._controller and self._session and self._session.agent_active:
                self._controller.request_stop()
                if self._session:
                    self._session.clear_remote_queue()
                respond("Stopped. Queued commands cleared.")
            else:
                respond("No active run to stop.")
        elif command == "resume":
            if self._session and not self._session.agent_active:
                self._session.queue_remote_command("run", "--resume")
                respond("Resume queued.")
            else:
                respond("Cannot resume right now.")

    def _queue_agent_command(self, command: str, args: str, respond) -> None:
        """Queue an agent command for REPL execution."""
        if self._session is None:
            respond("No active REPL session.")
            return

        if (
            command == "run"
            and self._session.agent_active
            and self._session.active_command == "run"
        ):
            respond("Run in progress. Stop first to start a new run.")
            return

        if self._session.agent_active:
            self._session.queue_remote_command(command, args)
            respond(
                f"/{command} queued — will run after"
                f" {self._session.active_command} finishes."
            )
        else:
            self._session.queue_remote_command(command, args)
            respond(f"/{command} queued.")
