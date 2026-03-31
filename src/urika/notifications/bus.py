"""NotificationBus — fan-out dispatcher for notification events."""

from __future__ import annotations

import logging
import os
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
    """Classify a remote command: read_only, run_control, agent, or rejected."""
    cmd = command.lower().strip().replace("/", "")
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

        # Paused
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
                for chunk in _split_message(text, max_len=4000):
                    respond(chunk)
                return

            if command == "run":
                self._run_remote_experiment(args, respond)
                return

            # Commands that can run via subprocess with --json or default args
            if command in ("evaluate", "plan", "finalize", "build-tool"):
                self._run_remote_cli_command(command, args, respond)
                return

            if command in ("report", "present"):
                # These prompt for experiment — pass most recent via --json
                self._run_remote_cli_command(command, args, respond)
                return

            # Fallback: queue for REPL
            self._session.queue_remote_command(command, args)
            respond(
                f"/{command} needs the REPL terminal to run. "
                f"It's queued and will execute when you interact with the REPL."
            )
        except Exception as exc:
            logger.warning("Remote %s failed: %s", command, exc)
            respond(f"Error: {exc}")
        finally:
            self._session.set_agent_idle()

    def _run_remote_advisor(self, question: str) -> str:
        """Run the advisor agent and return its text response.

        Includes conversation history from the REPL session and saves
        the exchange so the next call has context.
        """
        import asyncio
        import json as _json

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

        # Build context with conversation history (like REPL's _handle_free_text)
        context = f"Project: {self.project_name}\n"
        if self._session is not None:
            conv = getattr(self._session, "get_conversation_context", lambda: "")()
            if conv:
                context += f"\nPrevious conversation:\n{conv}\n"

        # Add project state summary
        methods_path = self._project_path / "methods.json"
        if methods_path.exists():
            try:
                mdata = _json.loads(methods_path.read_text(encoding="utf-8"))
                mlist = mdata.get("methods", [])
                context += f"\n{len(mlist)} methods tried.\n"
            except Exception:
                pass

        context += f"\nUser: {question}\n"

        try:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(runner.run(config, context))
            finally:
                loop.close()

            if result.success and result.text_output:
                text = result.text_output.strip()
                # Save to conversation history so next call has context
                if self._session is not None:
                    add_msg = getattr(self._session, "add_message", None)
                    if add_msg:
                        add_msg("user", question)
                        add_msg("advisor", text)
                # Save suggestions to file so /run subprocess can find them
                try:
                    from urika.orchestrator.parsing import parse_suggestions

                    parsed = parse_suggestions(text)
                    if parsed and parsed.get("suggestions"):
                        suggestions_dir = self._project_path / "suggestions"
                        suggestions_dir.mkdir(exist_ok=True)
                        pending_path = suggestions_dir / "pending.json"
                        import tempfile

                        # Atomic write
                        tmp_fd, tmp_path = tempfile.mkstemp(
                            dir=str(suggestions_dir), suffix=".tmp"
                        )
                        try:
                            with os.fdopen(tmp_fd, "w") as f:
                                import json as _json2

                                _json2.dump(parsed, f)
                            Path(tmp_path).rename(pending_path)
                        except Exception:
                            Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass  # Best-effort — don't break advisor response
                return text
            return f"Advisor error: {result.error or 'no response'}"
        except Exception as exc:
            return f"Advisor error: {exc}"

    def _run_remote_experiment(self, args: str, respond) -> None:
        """Run an experiment via subprocess with --auto (no interactive prompts).

        Sends progress updates back to the channel.
        """
        import subprocess
        import sys

        if self._project_path is None:
            respond("No project loaded.")
            return

        project_name = self._project_path.name

        # Parse args: /run, /run 3, /run --multi 5, /run --resume, /run focus on trees
        cmd = [sys.executable, "-m", "urika", "run", project_name, "--auto"]

        args_stripped = args.strip()
        if args_stripped:
            parts = args_stripped.split()
            if parts[0] == "--resume":
                cmd.append("--resume")
            elif parts[0] == "--multi" and len(parts) > 1:
                try:
                    n = int(parts[1])
                    cmd.extend(["--max-experiments", str(n)])
                    if len(parts) > 2:
                        cmd.extend(["--instructions", " ".join(parts[2:])])
                except ValueError:
                    cmd.extend(["--instructions", args_stripped])
            else:
                try:
                    max_turns = int(parts[0])
                    cmd.extend(["--max-turns", str(max_turns)])
                    if len(parts) > 1:
                        cmd.extend(["--instructions", " ".join(parts[1:])])
                except ValueError:
                    cmd.extend(["--instructions", args_stripped])

        desc_parts = [f"Starting experiment on {project_name}"]
        if "--max-experiments" in cmd:
            idx = cmd.index("--max-experiments")
            desc_parts.append(f"({cmd[idx + 1]} experiments)")
        if "--max-turns" in cmd:
            idx = cmd.index("--max-turns")
            desc_parts.append(f"(max {cmd[idx + 1]} turns)")
        if "--resume" in cmd:
            desc_parts = [f"Resuming experiment on {project_name}"]
        respond(" ".join(desc_parts) + "...")

        try:
            import time as _time

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "URIKA_REMOTE_RUN": "1"},
            )

            max_timeout = 6 * 3600  # 6 hours
            start_time = _time.monotonic()
            last_update = start_time
            output_lines: list[str] = []
            experiment_id = None

            # Read output line by line, forwarding progress
            for line in process.stdout:
                output_lines.append(line)
                elapsed = _time.monotonic() - start_time

                # Extract experiment ID from output
                if "Running experiment" in line and experiment_id is None:
                    parts = line.strip().split("Running experiment ")
                    if len(parts) > 1:
                        experiment_id = parts[1].split()[0]

                # Forward progress lines to Telegram (turn, agent, result events)
                stripped = line.strip()
                if stripped and not stripped.startswith("\x1b"):
                    now = _time.monotonic()
                    # Send updates at most every 30 seconds to avoid rate limits
                    if now - last_update > 30:
                        for marker in ("Turn ", "\u2713 ", "\u2717 ", "\u25b8 "):
                            if marker in stripped:
                                respond(stripped[:500])
                                last_update = now
                                break

                # Check timeout
                if elapsed > max_timeout:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    respond(f"Run timed out after {max_timeout // 3600} hours.")
                    if experiment_id:
                        _cleanup_experiment(self._project_path, experiment_id)
                    return

            process.wait()

            if process.returncode == 0:
                summary_lines = [
                    l.strip()
                    for l in output_lines[-20:]
                    if l.strip() and not l.strip().startswith("\x1b")
                ]
                summary = (
                    "\n".join(summary_lines[-10:])
                    if summary_lines
                    else "Run completed."
                )
                respond(f"Experiment finished:\n{summary}")
            else:
                error_lines = [l.strip() for l in output_lines[-10:] if l.strip()]
                error = "\n".join(error_lines) or "Unknown error"
                respond(f"Run failed:\n{error[:2000]}")
                if experiment_id:
                    _cleanup_experiment(self._project_path, experiment_id)

        except Exception as exc:
            respond(f"Run error: {exc}")

    def _run_remote_cli_command(self, command: str, args: str, respond) -> None:
        """Run a CLI command via subprocess with --json to avoid interactive prompts."""
        import subprocess
        import sys
        import json as _json

        if self._project_path is None:
            respond("No project loaded.")
            return

        project_name = self._project_path.name

        # Build command
        cmd_map = {
            "evaluate": ["evaluate", project_name],
            "plan": ["plan", project_name],
            "finalize": ["finalize", project_name],
            "report": ["report", project_name],
            "present": ["present", project_name],
            "build-tool": ["build-tool", project_name],
        }

        base = cmd_map.get(command)
        if base is None:
            respond(f"Unknown command: /{command}")
            return

        cmd = [sys.executable, "-m", "urika"] + base + ["--json"]

        # Add args as experiment ID or instructions
        args_stripped = args.strip()
        if args_stripped:
            if command in ("evaluate", "plan", "report", "present"):
                # Could be experiment ID (exp-NNN) or instructions
                if args_stripped.startswith("exp-"):
                    cmd.extend(["--experiment", args_stripped])
                else:
                    cmd.extend(["--instructions", args_stripped])
            elif command == "finalize":
                cmd.extend(["--instructions", args_stripped])
            elif command == "build-tool":
                # build-tool takes instructions as positional arg
                # Remove --json, add instructions before it
                cmd = [
                    sys.executable,
                    "-m",
                    "urika",
                    "build-tool",
                    project_name,
                    args_stripped,
                    "--json",
                ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max for single agent commands
                env={**__import__("os").environ, "URIKA_REMOTE_RUN": "1"},
            )

            if result.returncode == 0:
                # Try to parse JSON output
                output = result.stdout.strip()
                try:
                    data = _json.loads(output)
                    text = data.get("output", data.get("path", str(data)))
                    respond(f"/{command} completed:\n{text[:3000]}")
                except _json.JSONDecodeError:
                    respond(f"/{command} completed:\n{output[-1000:]}")
            else:
                error = result.stderr.strip() or result.stdout.strip()
                respond(f"/{command} failed:\n{error[:1000]}")
        except subprocess.TimeoutExpired:
            respond(f"/{command} timed out.")
        except Exception as exc:
            respond(f"/{command} error: {exc}")
