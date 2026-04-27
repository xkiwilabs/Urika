"""NotificationBus — fan-out dispatcher for notification events."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from urika.notifications.base import NotificationChannel
    from urika.orchestrator.pause import PauseController

from urika.notifications.events import NotificationEvent

# ---------------------------------------------------------------------------
# Per-command help text
# ---------------------------------------------------------------------------

_COMMAND_HELP: dict[str, str] = {
    "run": (
        "/run [options]\n"
        "  Start an experiment run (always auto, no prompts).\n\n"
        "  /run                  single experiment, default turns\n"
        "  /run 3                single experiment, 3 turns max\n"
        "  /run --multi 5        5 experiments autonomously\n"
        "  /run --resume         resume paused/stopped experiment\n"
        "  /run try tree models  single experiment with instructions\n"
        "  /run --multi 3 focus on feature selection\n"
        "                        3 experiments with instructions\n\n"
        "  Stop with /stop. Pause with /pause."
    ),
    "advisor": (
        "/advisor <question>\n"
        "  Ask the advisor agent about the project.\n"
        "  Only works when no agent is running.\n\n"
        "  /advisor what should I try next?\n"
        "  /advisor should I use non-parametric tests?"
    ),
    "evaluate": (
        "/evaluate [experiment_id]\n"
        "  Run the evaluator on an experiment.\n"
        "  Default: most recent experiment.\n\n"
        "  /evaluate\n"
        "  /evaluate exp-003"
    ),
    "plan": (
        "/plan [experiment_id]\n"
        "  Run the planning agent.\n"
        "  Default: most recent experiment.\n\n"
        "  /plan\n"
        "  /plan exp-003"
    ),
    "report": (
        "/report [experiment_id]\n"
        "  Generate a labbook report.\n"
        "  Default: most recent experiment.\n\n"
        "  /report\n"
        "  /report exp-003"
    ),
    "present": (
        "/present [experiment_id]\n"
        "  Generate a reveal.js presentation.\n"
        "  Default: most recent experiment.\n\n"
        "  /present\n"
        "  /present exp-003"
    ),
    "finalize": (
        "/finalize [instructions]\n"
        "  Run the finalizer — standalone methods, findings, report.\n\n"
        "  /finalize\n"
        "  /finalize focus on the ensemble methods"
    ),
    "build-tool": (
        "/build-tool <description>\n"
        "  Create a custom analysis tool.\n\n"
        "  /build-tool create an ICC tool using pingouin\n"
        "  /build-tool install mne and add an EEG epoch extractor"
    ),
    "status": "/status\n  Project overview: experiments, runs, completion state.",
    "results": "/results\n  Leaderboard — top methods ranked by primary metric.",
    "methods": "/methods\n  Last 10 registered methods with status and metrics.",
    "criteria": "/criteria\n  Current success criteria and version.",
    "experiments": "/experiments\n  Last 10 experiments with status and run counts.",
    "logs": (
        "/logs [experiment_id]\n"
        "  Last 5 run logs. Default: most recent experiment.\n\n"
        "  /logs\n"
        "  /logs exp-003"
    ),
    "usage": "/usage\n  Token counts, cost, agent calls, session stats.",
    "pause": "/pause\n  Pause the active run after the current turn completes.",
    "stop": "/stop\n  Stop the active run immediately. Clears queued commands.",
    "resume": "/resume\n  Resume a paused or stopped experiment.",
}


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split long text into chunks that fit chat platform limits.

    Splits on newlines when possible to avoid breaking mid-sentence.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a newline near the limit to split cleanly
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            # No good newline — split at limit
            split_at = max_len
        chunk = text[:split_at].rstrip()
        chunks.append(chunk)
        text = text[split_at:].lstrip("\n")

    return chunks


def _help_text(topic: str = "") -> str:
    """Return help text — general or for a specific command."""
    if topic and topic.lstrip("/") in _COMMAND_HELP:
        return _COMMAND_HELP[topic.lstrip("/")]

    return (
        "Available remote commands:\n\n"
        "Read-only:\n"
        "  /status /results /methods /criteria\n"
        "  /experiments /logs /usage\n\n"
        "Run control:\n"
        "  /pause /stop /resume\n\n"
        "Agent commands:\n"
        "  /run /advisor /evaluate /plan\n"
        "  /report /present /finalize /build-tool\n\n"
        "Type /help <command> for details."
    )


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
    """Classify a remote command: read_only, run_control, agent, ask, or rejected."""
    cmd = command.lower().strip().replace("/", "")
    if cmd == "ask":
        return "ask"
    if cmd in _READ_ONLY_COMMANDS:
        return "read_only"
    if cmd in _RUN_CONTROL_COMMANDS:
        return "run_control"
    if cmd in _AGENT_COMMANDS:
        return "agent"
    return "rejected"


def _cleanup_experiment(project_path: Path, experiment_id: str) -> None:
    """Clean up lock and session after a failed remote run."""
    try:
        from urika.core.session import fail_session, release_lock

        try:
            fail_session(project_path, experiment_id, error="Remote run terminated")
        except Exception:
            pass
        release_lock(project_path, experiment_id)
    except Exception:
        pass


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
        """Start the dispatch thread and channel listeners.

        Runs ``health_check()`` on each channel before starting its listener.
        Channels that fail the health check are removed from ``self.channels``
        with a WARNING log — subsequent ``notify()`` calls will skip them.
        """
        self._controller = controller
        self._session = session
        self._thread = threading.Thread(
            target=self._dispatch_loop, name="urika-notifications", daemon=True
        )
        self._thread.start()

        # Filter out unhealthy channels so dispatch and listeners only run on
        # configurations we've actually verified can talk to the remote service.
        healthy_channels: list[NotificationChannel] = []
        for ch in self.channels:
            try:
                ok, msg = ch.health_check()
            except Exception as exc:
                ok, msg = False, f"health check raised: {exc}"
            if not ok:
                logger.warning(
                    "Channel %s failed health check: %s — will not dispatch",
                    type(ch).__name__,
                    msg,
                )
                continue
            healthy_channels.append(ch)
        self.channels = healthy_channels

        for ch in self.channels:
            try:
                ch.start_listener(controller, project_path=self._project_path, bus=self)
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
        """Map an on_progress event to a NotificationEvent, or None to skip.

        Only experiment-level events generate notifications — no per-turn
        or per-run noise. Users get notified when experiments start, complete,
        fail, or are paused.
        """
        # Track turn for context but don't notify
        if event == "turn":
            self._turn = detail
            return None

        # Criteria met — important milestone
        if event == "result" and "Criteria met" in detail:
            return NotificationEvent(
                event_type="criteria_met",
                project_name=self.project_name,
                experiment_id=self._experiment_id,
                summary=detail,
                priority="high",
            )

        # Run status events from end-of-experiment phase messages.
        # These are also emitted directly by cli/run.py — TUI/dashboard
        # orchestrator flows that don't go through the CLI need them here.
        # Priorities mirror EVENT_METADATA in events.py.
        # NOTE: the specific "Experiment paused" check must run BEFORE the
        # generic "Paused" fallback below so it takes precedence.
        if event == "phase":
            if "Experiment completed" in detail:
                return NotificationEvent(
                    event_type="experiment_completed",
                    project_name=self.project_name,
                    experiment_id=self._experiment_id,
                    summary=detail,
                    priority="high",
                )
            if "Experiment failed" in detail:
                return NotificationEvent(
                    event_type="experiment_failed",
                    project_name=self.project_name,
                    experiment_id=self._experiment_id,
                    summary=detail,
                    priority="high",
                )
            if "Experiment paused" in detail:
                return NotificationEvent(
                    event_type="experiment_paused",
                    project_name=self.project_name,
                    experiment_id=self._experiment_id,
                    summary=detail,
                    priority="medium",
                )
            if "Experiment stopped" in detail:
                return NotificationEvent(
                    event_type="experiment_stopped",
                    project_name=self.project_name,
                    experiment_id=self._experiment_id,
                    summary=detail,
                    priority="medium",
                )

        # Paused (generic fallback — covers any other "Paused" phase text)
        if event == "phase" and "Paused" in detail:
            return NotificationEvent(
                event_type="paused",
                project_name=self.project_name,
                experiment_id=self._experiment_id,
                summary=detail,
                priority="medium",
            )

        # New experiment starting (from meta-orchestrator)
        if event == "phase" and "Starting experiment" in detail:
            return NotificationEvent(
                event_type="experiment_started",
                project_name=self.project_name,
                summary=detail,
                priority="medium",
            )

        # Skip everything else (turns, agent activity, run records, tool use)
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
        self, command: str, args: str = "", respond: Callable[..., Any] | None = None
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

        if category == "ask":
            # Free text for the orchestrator — queue as "ask" command
            self._queue_agent_command("ask", args, _respond)
            return

        if category == "read_only":
            text = self._execute_read_only(command, args)
            for chunk in _split_message(text, max_len=4000):
                _respond(chunk)
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
            return _help_text(args.strip())
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
        """Queue an agent command for TUI/REPL execution.

        All agent commands are queued for the drain mechanism,
        which executes them with full terminal output.
        """
        if self._session is None:
            respond("No active session.")
            return

        if (
            command == "run"
            and self._session.agent_active
            and self._session.active_command == "run"
        ):
            respond("Run in progress. Stop first to start a new run.")
            return

        self._session.queue_remote_command(command, args, respond)
        if self._session.agent_active:
            if command == "ask":
                respond(
                    f"Question queued \u2014 will answer after"
                    f" {self._session.active_command} finishes."
                )
            else:
                respond(
                    f"/{command} queued \u2014 will run after"
                    f" {self._session.active_command} finishes."
                )
        else:
            if command == "ask":
                respond("Thinking…")
            else:
                respond(f"/{command} queued \u2014 executing shortly...")


