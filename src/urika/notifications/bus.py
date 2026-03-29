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

# ---------------------------------------------------------------------------
# Per-command help text
# ---------------------------------------------------------------------------

_COMMAND_HELP: dict[str, str] = {
    "run": (
        "/run [options]\n"
        "  Start an experiment run.\n\n"
        "  /run              single experiment, default turns\n"
        "  /run 3            single experiment, 3 turns max\n"
        "  /run --multi 5    5 experiments autonomously\n"
        "  /run --resume     resume paused/stopped experiment\n\n"
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

        # Print to terminal so there's a record
        import sys

        cmd_display = f"/{command} {args}".strip()
        sys.stdout.write(f"\n  \033[33m[Remote]\033[0m {cmd_display}\n")
        sys.stdout.flush()

        if category == "rejected":
            _respond(f"/{command} is not available remotely. Use the terminal.")
            return

        if category == "read_only":
            text = self._execute_read_only(command, args)
            if len(text) > 3500:
                text = text[:3500] + "\n\n[Truncated — use terminal for full output]"
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
        """Queue or execute an agent command.

        If idle: execute in a background thread and send result back.
        If busy: queue for REPL to drain after current command finishes.
        """
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
                f"/{command} queued \u2014 will run after"
                f" {self._session.active_command} finishes."
            )
        else:
            # Idle: execute immediately in background thread
            _agent_hints = {
                "advisor": "thinking — may take a few minutes",
                "run": "starting experiment — this will take a while",
                "evaluate": "evaluating — may take a minute",
                "plan": "designing method — may take a minute",
                "report": "writing report — may take a few minutes",
                "present": "creating presentation — may take a few minutes",
                "finalize": "finalizing project — this will take a while",
                "build-tool": "building tool — may take a few minutes",
            }
            hint = _agent_hints.get(command, "working")
            respond(f"Running /{command} ({hint})...")
            thread = threading.Thread(
                target=self._run_agent_in_background,
                args=(command, args, respond),
                name=f"urika-remote-{command}",
                daemon=True,
            )
            thread.start()

    def _run_agent_in_background(self, command: str, args: str, respond) -> None:
        """Execute an agent command in a background thread."""
        if self._session is None or self._project_path is None:
            respond("No active session.")
            return

        self._session.set_agent_active(command)
        try:
            if command in (
                "status",
                "results",
                "methods",
                "criteria",
                "experiments",
                "logs",
                "usage",
            ):
                # These are read-only — shouldn't reach here but handle gracefully
                text = self._execute_read_only(command, args)
                respond(text)
                return

            if command == "advisor":
                text = self._run_remote_advisor(args)
                respond(text)
                return

            # For run, evaluate, plan, report, present, finalize, build-tool:
            # Queue for REPL — these need the full CLI machinery
            self._session.queue_remote_command(command, args)
            respond(
                f"/{command} requires the terminal. "
                f"Queued \u2014 press Enter in the REPL to execute."
            )
        except Exception as exc:
            logger.warning("Remote %s failed: %s", command, exc)
            respond(f"Error: {exc}")
        finally:
            self._session.set_agent_idle()

    def _run_remote_advisor(self, question: str) -> str:
        """Run the advisor agent and return its text response."""
        import asyncio

        try:
            from urika.agents.registry import AgentRegistry
            from urika.agents.runner import get_runner
        except ImportError:
            return "Agent SDK not available."

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()
        advisor = registry.get("advisor_agent")
        if advisor is None:
            return "Advisor agent not found."

        config = advisor.build_config(project_dir=self._project_path, experiment_id="")
        config.max_turns = 25

        try:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(runner.run(config, question))
            finally:
                loop.close()

            if result.success and result.text_output:
                text = result.text_output.strip()
                if len(text) > 3500:
                    text = text[:3500] + "\n\n[Truncated]"
                return text
            return f"Advisor error: {result.error or 'no response'}"
        except Exception as exc:
            return f"Advisor error: {exc}"
