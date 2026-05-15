"""ThinkingPanel and Spinner — long-running-operation UI components.

Split out of cli_display.py as part of Phase 8 refactoring. Both
classes are self-contained UI affordances:

    ThinkingPanel  pins a 2-line status panel to the terminal bottom
                   via a scroll region; updated by the orchestrator
                   while a long-running command is in flight.
    Spinner        a synchronous context-manager spinner for shorter
                   operations (single agent calls, bulk file copies).

They import their constants and helpers from ``cli_display`` so the
visual style stays consistent. The base module re-exports them at the
bottom for back-compat with existing imports.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
import time

from urika.cli_display import (
    _AGENT_COLORS,
    _AGENT_LABELS,
    _C,
    _SPINNER,
    _TOOL_VERBS,
    _format_duration,
    _is_tty,
    format_model_source,
)


class ThinkingPanel:
    """Persistent 2-line panel pinned to terminal bottom via scroll region.

    Line 1: empty padding
    Line 2: spinner + agent + activity verb ... project + model + elapsed

    Uses threading.Thread for the spinner so it works during asyncio.run() calls.
    All ANSI writes are wrapped in try/except for safety.
    """

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.project = ""
        self.agent = ""
        self.model = ""
        self.turn = ""
        self.experiment_id = ""
        self.pause_requested = False
        self.activity = "Thinking\u2026"
        self._active = False
        self._rows = 0
        self._cols = 0
        self._spin_idx = 0
        self._spin_slow_counter = 0
        self._spin_slow_idx = 0
        self._lock = threading.Lock()
        self._spin_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._project_dir: object = None  # set via update()

    def activate(self) -> None:
        """Set up scroll region, reserving 4 bottom lines.

        Call BEFORE any print() output. Becomes a no-op if terminal is
        too small (< 10 rows) or not a TTY.
        """
        if not _is_tty():
            return
        try:
            size = os.get_terminal_size()
            self._rows = size.lines
            self._cols = size.columns
        except OSError:
            return
        if self._rows < 10:
            return
        try:
            self._active = True
            # Set scroll region without clearing screen (preserves scroll history)
            sys.stdout.write(f"\033[1;{self._rows - 4}r\033[{self._rows - 5};1H")
            sys.stdout.flush()
            atexit.register(self.cleanup)
            # Handle terminal resize (SIGWINCH is Unix-only)
            import signal

            if hasattr(signal, "SIGWINCH"):
                self._prev_winch = signal.getsignal(signal.SIGWINCH)

                def _on_resize(signum: int, frame: object) -> None:
                    try:
                        size = os.get_terminal_size()
                        with self._lock:
                            self._rows = size.lines
                            self._cols = size.columns
                            if self._rows >= 10:
                                sys.stdout.write(
                                    f"\033[1;{self._rows - 4}r\033[{self._rows - 5};1H"
                                )
                                sys.stdout.flush()
                                self._render()
                    except (OSError, ValueError):
                        pass

                signal.signal(signal.SIGWINCH, _on_resize)
        except (OSError, ValueError):
            self._active = False

    def start_spinner(self) -> None:
        """Start background spinner animation thread."""
        if not self._active or self._spin_thread is not None:
            return
        self._stop_event.clear()
        self._spin_thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._spin_thread.start()

    def _spin_loop(self) -> None:
        """Animate spinner character at ~8 Hz."""
        while not self._stop_event.is_set():
            self._stop_event.wait(0.12)
            if self._stop_event.is_set():
                break
            with self._lock:
                if self._active:
                    self._spin_idx = (self._spin_idx + 1) % len(_SPINNER)
                    self._spin_slow_counter += 1
                    if self._spin_slow_counter >= 5:  # ~600ms per frame
                        self._spin_slow_counter = 0
                        self._spin_slow_idx = (self._spin_slow_idx + 1) % len(_SPINNER)
                    self._render()

    def _render(self) -> None:
        """Draw the 2 reserved rows below the scroll region.

        Line 1: separator
        Line 2: experiment + turn (+ pause warning if requested)
        Line 3: spinner + agent + verb ... project + model + elapsed
        Line 4: empty padding

        Must be called with self._lock held or from a safe context.
        """
        if not self._active:
            return
        try:
            elapsed = _format_duration(int((time.monotonic() - self.start) * 1000))

            # ── Line 2: experiment + turn info ──
            info_parts = []
            if self.experiment_id:
                info_parts.append(
                    f"{_C.ORANGE}Experiment:{_C.RESET} {self.experiment_id}"
                )
            if self.turn:
                info_parts.append(f"{_C.ORANGE}{self.turn}{_C.RESET}")
            if self.pause_requested:
                info_parts.append(
                    f"{_C.YELLOW}\u23f8 Pausing after this turn\u2026{_C.RESET}"
                )
            # Always show something — fallback to activity summary
            if not info_parts:
                info_parts.append(f"{_C.DIM}{self.activity}{_C.RESET}")
            slow_ch = _SPINNER[self._spin_slow_idx % len(_SPINNER)]
            sep_dot = f" {_C.DIM}\u00b7{_C.RESET} "
            info_line = f"  {_C.ORANGE}{slow_ch}{_C.RESET} {sep_dot.join(info_parts)}"

            # ── Line 3: spinner + agent + activity ──
            ch = _SPINNER[self._spin_idx]
            agent_color = _AGENT_COLORS.get(self.agent, _C.BLUE)
            agent_label = _AGENT_LABELS.get(self.agent, self.agent)
            left = (
                f"  {_C.BLUE}{ch}{_C.RESET}"
                f" {agent_color}{agent_label}{_C.RESET}"
                f" {_C.BLUE}\u00b7 {self.activity}{_C.RESET}"
            )

            # Right side: project (dim) + model (cyan) + elapsed (red)
            right_parts = []
            if self.project:
                right_parts.append(f"{_C.DIM}{self.project}{_C.RESET}")
            if self.model:
                right_parts.append(f"{_C.CYAN}{self.model}{_C.RESET}")
            right_parts.append(f"{_C.RED}{elapsed}{_C.RESET}")
            right = f" {_C.DIM}\u00b7{_C.RESET} ".join(right_parts)

            sep = "\u2500" * self._cols
            buf = "\0337"  # save cursor
            # Line 1: separator
            buf += f"\033[{self._rows - 3};1H\033[K{_C.DIM}{sep}{_C.RESET}"
            # Line 2: experiment + turn info
            buf += f"\033[{self._rows - 2};1H\033[K{info_line}"
            # Line 3: agent status line
            buf += f"\033[{self._rows - 1};1H\033[K{left}  {right}"
            # Line 4: empty padding
            buf += f"\033[{self._rows};1H\033[K"
            buf += "\0338"  # restore cursor
            sys.stdout.write(buf)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass

    def render(self) -> None:
        """Public render with spin index reset."""
        with self._lock:
            self._spin_idx = 0
            self._render()

    def update(
        self,
        agent: str = "",
        activity: str = "",
        turn: str = "",
        project: str = "",
        model: str = "",
        project_dir: object = None,
        experiment_id: str = "",
        pause_requested: bool | None = None,
    ) -> None:
        """Update panel fields and re-render.

        Only non-empty values are updated; pass empty string to keep current.
        """
        with self._lock:
            if agent:
                self.agent = agent
            if activity:
                self.activity = activity
            if turn:
                self.turn = turn
            if project:
                self.project = project
            if project_dir is not None:
                self._project_dir = project_dir
            if experiment_id:
                self.experiment_id = experiment_id
            if pause_requested is not None:
                self.pause_requested = pause_requested
            if model:
                self.model = format_model_source(model, project_dir=self._project_dir)
            self._spin_idx = 0
            self._render()

    def set_thinking(self, text: str) -> None:
        """Update the activity verb from a tool name or raw text."""
        with self._lock:
            # Map tool names to short verbs
            self.activity = _TOOL_VERBS.get(text, text)
            self._render()

    def set_model(self, model: str) -> None:
        """Update the model name (e.g. from AssistantMessage.model)."""
        with self._lock:
            self.model = format_model_source(model, project_dir=self._project_dir)
            self._render()

    def cleanup(self) -> None:
        """Reset scroll region and clear panel rows. Always safe to call."""
        self._stop_event.set()
        if self._spin_thread is not None:
            self._spin_thread.join(timeout=1)
            self._spin_thread = None
        if not self._active:
            return
        self._active = False
        try:
            # Restore SIGWINCH handler (Unix-only)
            import signal

            if hasattr(signal, "SIGWINCH") and hasattr(self, "_prev_winch"):
                signal.signal(signal.SIGWINCH, self._prev_winch)
        except (OSError, ValueError):
            pass
        try:
            # Clear the 4 reserved lines
            sys.stdout.write(f"\033[{self._rows - 3};1H\033[K")
            sys.stdout.write(f"\033[{self._rows - 2};1H\033[K")
            sys.stdout.write(f"\033[{self._rows - 1};1H\033[K")
            sys.stdout.write(f"\033[{self._rows};1H\033[K")
            # Restore full scroll region and position cursor
            sys.stdout.write(f"\033[r\033[{self._rows - 4};1H")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass


# ── Sync spinner context manager ─────────────────────────────────


class Spinner:
    """Synchronous spinner for long operations.

    Supports printing lines above the spinner while it runs, and
    updating the spinner message dynamically. The spinner character
    freezes in place when a new line is printed above, creating a
    visual pattern in the terminal.

    When ``session_info`` is provided, the spinner line shows session
    details on the right side (project, model, elapsed time, cost).

    Usage:
        with Spinner("Working") as sp:
            sp.print_above("  ▸ Step 1 done")
            sp.update("Still working")

        with Spinner("Thinking", session_info={"project": "my-proj"}) as sp:
            sp.update_session(model="claude-3", cost=0.12)
    """

    def __init__(
        self,
        message: str,
        *,
        session_info: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> None:
        self.message = message
        self._active = False
        self._thread: threading.Thread | None = None
        self._lock: threading.Lock | None = None
        # Session info shown on the right side of the spinner line
        self._project: str = ""
        self._model: str = ""
        self._cost: float = 0.0
        self._start: float = time.monotonic()
        if session_info is not None:
            self._project = str(session_info.get("project", ""))
            self._model = str(session_info.get("model", ""))
            self._cost = float(session_info.get("cost", 0.0) or 0.0)

    def __enter__(self) -> Spinner:
        if not _is_tty():
            print(f"  {self.message}")
            return self
        self._active = True
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._active = False
        if self._thread is not None:
            self._thread.join(timeout=1)
        if _is_tty():
            try:
                sys.stdout.write("\r\033[K\033[0m")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass

    def update(self, message: str) -> None:
        """Update the spinner message."""
        if self._lock is not None:
            with self._lock:
                self.message = message
        else:
            self.message = message

    def update_session(self, **kwargs: object) -> None:
        """Update session info fields and re-render on the next tick.

        Accepted keyword arguments: ``model``, ``cost``, ``project``.
        """

        def _apply() -> None:
            if "model" in kwargs and kwargs["model"]:
                raw = str(kwargs["model"])
                if "/" in raw:
                    raw = raw.split("/")[-1]
                if len(raw) > 25:
                    raw = raw[:22] + "\u2026"
                self._model = raw
            if "cost" in kwargs and kwargs["cost"] is not None:
                self._cost = float(kwargs["cost"])  # type: ignore[arg-type]
            if "project" in kwargs and kwargs["project"]:
                self._project = str(kwargs["project"])

        if self._lock is not None:
            with self._lock:
                _apply()
        else:
            _apply()

    def print_above(self, text: str) -> None:
        """Print a line above the spinner, keeping the spinner on the last line."""
        if not _is_tty():
            print(text)
            return

        def _write() -> None:
            try:
                sys.stdout.write(f"\r\033[K{text}\n")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass

        if self._lock is not None:
            with self._lock:
                _write()
        else:
            _write()

    def _build_right_info(self) -> str:
        """Build the right-side session info string (plain text, no ANSI)."""
        parts: list[str] = []
        if self._project:
            parts.append(self._project)
        if self._model:
            parts.append(self._model)
        elapsed_ms = int((time.monotonic() - self._start) * 1000)
        parts.append(_format_duration(elapsed_ms))
        if self._cost > 0:
            parts.append(f"~${self._cost:.2f}")
        return " \u00b7 ".join(parts)

    def _spin(self) -> None:
        idx = 0
        while self._active:
            ch = _SPINNER[idx % len(_SPINNER)]
            if self._lock is not None:
                with self._lock:
                    msg = self.message
                    right_info = (
                        self._build_right_info() if self._project or self._model else ""
                    )
            else:
                msg = self.message
                right_info = (
                    self._build_right_info() if self._project or self._model else ""
                )
            try:
                if right_info:
                    # Get terminal width for right-alignment
                    try:
                        cols = os.get_terminal_size().columns
                    except OSError:
                        cols = 80
                    # Left: "  <spinner> <message>"
                    left_visible = 2 + 1 + 1 + len(msg)  # "  " + ch + " " + msg
                    right_visible = len(right_info)
                    gap = max(2, cols - left_visible - right_visible)
                    sys.stdout.write(
                        f"\r  {_C.CYAN}{ch}{_C.RESET} {_C.DIM}{msg}{_C.RESET}"
                        f"{' ' * gap}"
                        f"{_C.DIM}{right_info}{_C.RESET}\033[K"
                    )
                else:
                    sys.stdout.write(
                        f"\r  {_C.CYAN}{ch}{_C.RESET} {_C.DIM}{msg}{_C.RESET}\033[K"
                    )
                sys.stdout.flush()
            except (OSError, ValueError):
                break
            idx += 1
            time.sleep(0.12)
