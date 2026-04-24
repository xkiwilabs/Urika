"""REPL session state — project context, advisor conversation, usage tracking."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ReplSession:
    """Manages state for an interactive REPL session."""

    project_path: Path | None = None
    project_name: str | None = None
    conversation: list[dict[str, str]] = field(default_factory=list)

    # Input queue — lets users type while agents run
    _input_queue: list[str] = field(default_factory=list)

    # Advisor suggestions — parsed from advisor output, used by /run
    pending_suggestions: list[dict] = field(default_factory=list)

    # Notification bus — persistent, lives across runs
    notification_bus: object = None  # NotificationBus | None (avoid circular import)

    # Privacy endpoint state — False blocks agent commands in hybrid/private mode
    _private_endpoint_ok: bool = True

    # Agent activity — tracks if any command is running
    agent_active: bool = False
    active_command: str = ""

    # Remote command queue — commands from Telegram/Slack
    # Each item is (command, args, respond) where respond is an optional callback
    _remote_queue: list[tuple[str, str, object]] = field(default_factory=list)
    _remote_lock: threading.Lock = field(default_factory=threading.Lock)

    # Remote command state — set during remote command execution
    _is_remote_command: bool = False
    _remote_respond: object = None  # Callable[[str], None] | None

    # Orchestrator session — for persistence
    _orch_session: object = None  # OrchestratorSession | None

    # Usage tracking
    session_start: float = field(default_factory=time.monotonic)
    session_start_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    agent_calls: int = 0
    experiments_run: int = 0
    model: str = ""

    # Agent activity state — updated by background threads, read by toolbar
    agent_running: bool = False
    agent_name: str = ""
    agent_activity: str = ""
    agent_turn: str = ""
    agent_error: str = ""
    _agent_lock: threading.Lock = field(default_factory=threading.Lock)

    # Processing-time accumulator. Only ticks while agent_running is
    # True. Updated by set_agent_running / set_agent_idle.
    _processing_start: float = 0.0
    total_processing_ms: int = 0

    # Ring buffer of recent output-panel lines for the /copy slash command.
    # Capped because agents can produce thousands of lines per run — we only
    # need enough history for "copy what's on screen / just scrolled past".
    recent_output_lines: list[str] = field(default_factory=list)
    _recent_output_cap: int = 1000

    @property
    def has_project(self) -> bool:
        return self.project_path is not None

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.session_start) * 1000)

    @property
    def processing_ms(self) -> int:
        """Total time spent processing (agents running). Only ticks
        while ``agent_running`` is True. Returns accumulated time
        from previous runs + the current run's elapsed time."""
        total = self.total_processing_ms
        if self._processing_start > 0:
            total += int((time.monotonic() - self._processing_start) * 1000)
        return total

    @property
    def has_queued_input(self) -> bool:
        """Check if there's queued user input."""
        return len(self._input_queue) > 0

    def queue_input(self, text: str) -> None:
        """Queue user input for injection into the next agent call."""
        if text.strip():
            self._input_queue.append(text.strip())

    def pop_queued_input(self) -> str:
        """Pop all queued input as a single string. Clears the queue."""
        if not self._input_queue:
            return ""
        combined = "\n".join(self._input_queue)
        self._input_queue.clear()
        return combined

    def load_project(self, path: Path, name: str) -> None:
        self.save_usage()  # save current project's usage first
        self.project_path = path
        self.project_name = name
        self.conversation = []
        self.pending_suggestions = []
        # Reset usage for new project
        self.session_start = time.monotonic()
        self.session_start_iso = datetime.now(timezone.utc).isoformat()
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost_usd = 0.0
        self.agent_calls = 0
        self.experiments_run = 0
        # Reset command activity and remote queue
        with self._remote_lock:
            self._remote_queue.clear()
        self.agent_active = False
        self.active_command = ""

    def clear_project(self) -> None:
        self.project_path = None
        self.project_name = None
        self.conversation = []

    def add_message(self, role: str, text: str) -> None:
        self.conversation.append({"role": role, "text": text})

    def get_conversation_context(self, max_exchanges: int = 10) -> str:
        recent = self.conversation[-max_exchanges:]
        lines = []
        for msg in recent:
            prefix = "User" if msg["role"] == "user" else "Advisor"
            lines.append(f"{prefix}: {msg['text']}")
        return "\n".join(lines)

    def record_agent_call(
        self,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        model: str = "",
    ) -> None:
        """Record an agent call's usage stats."""
        self.agent_calls += 1
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost_usd
        if model:
            self.model = model

    def record_output_line(self, line: str) -> None:
        """Append a rendered output line to the recent-output buffer.

        Called from the TUI's output capture so the /copy slash command
        can read back the last N lines as a clipboard fallback for
        terminals that don't forward Shift+drag.
        """
        self.recent_output_lines.append(line)
        if len(self.recent_output_lines) > self._recent_output_cap:
            # Drop the oldest lines in a single slice — cheaper than
            # popleft-in-a-loop and avoids importing deque for what is
            # really just a cap-and-trim.
            overflow = len(self.recent_output_lines) - self._recent_output_cap
            del self.recent_output_lines[:overflow]

    def set_agent_running(
        self,
        agent_name: str = "",
        activity: str = "",
    ) -> None:
        """Mark an agent as running (called from background thread)."""
        with self._agent_lock:
            self.agent_running = True
            self.agent_name = agent_name
            self.agent_activity = activity or "Working\u2026"
            self.agent_turn = ""
            self.agent_error = ""
            self._processing_start = time.monotonic()

    def set_agent_active(self, command: str) -> None:
        """Mark an agent command as active."""
        with self._agent_lock:
            self.agent_active = True
            self.active_command = command

    def set_agent_idle(self, error: str = "") -> None:
        """Mark the agent as finished (called from background thread)."""
        with self._agent_lock:
            # Accumulate processing time
            if self._processing_start > 0:
                self.total_processing_ms += int(
                    (time.monotonic() - self._processing_start) * 1000
                )
                self._processing_start = 0.0
            self.agent_running = False
            self.agent_name = ""
            self.agent_activity = ""
            self.agent_turn = ""
            self.agent_error = error
            self.agent_active = False
            self.active_command = ""

    def set_agent_inactive(self) -> None:
        """Mark the agent command as inactive (alias for set_agent_idle)."""
        self.set_agent_idle()

    def update_agent_activity(
        self,
        activity: str = "",
        turn: str = "",
        model: str = "",
    ) -> None:
        """Update agent activity fields (called from background thread)."""
        with self._agent_lock:
            if activity:
                self.agent_activity = activity
            if turn:
                self.agent_turn = turn
            if model:
                self.model = model

    # ── Remote command queue ────────────────────────────────────

    @property
    def has_remote_command(self) -> bool:
        """Check if there are queued remote commands."""
        with self._remote_lock:
            return len(self._remote_queue) > 0

    def queue_remote_command(
        self, command: str, args: str, respond: object = None
    ) -> None:
        """Queue a command from Telegram/Slack for REPL execution.

        Args:
            command: command name (e.g. "run", "evaluate")
            args: command arguments
            respond: optional callback(text) to send results back to the channel
        """
        with self._remote_lock:
            self._remote_queue.append((command, args, respond))

    def pop_remote_command(self) -> tuple[str, str, object] | None:
        """Pop the next remote command, or None if empty.

        Returns (command, args, respond) tuple or None.
        """
        with self._remote_lock:
            if self._remote_queue:
                return self._remote_queue.pop(0)
            return None

    def clear_remote_queue(self) -> None:
        """Clear all queued remote commands."""
        with self._remote_lock:
            self._remote_queue.clear()

    def save_usage(self) -> None:
        """Save session usage to project's usage.json."""
        if not self.has_project:
            return
        from urika.core.usage import record_session

        record_session(
            self.project_path,
            started=self.session_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=self.elapsed_ms,
            tokens_in=self.total_tokens_in,
            tokens_out=self.total_tokens_out,
            cost_usd=self.total_cost_usd,
            agent_calls=self.agent_calls,
            experiments_run=self.experiments_run,
        )
