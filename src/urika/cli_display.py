"""Terminal display for Urika CLI — header, spinner, status bar.

Pure ANSI escape sequences, no external dependencies.
Gracefully degrades when stdout is not a TTY.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import sys
import time


def _reset_terminal() -> None:
    """Reset terminal colors and attributes on exit."""
    try:
        if sys.stdout.isatty():
            sys.stdout.write("\033[0m\033[?25h")  # reset attrs + show cursor
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


# Ensure terminal is reset even on crashes or Ctrl+C
atexit.register(_reset_terminal)


class _C:
    """ANSI color codes."""

    CYAN = "\033[36m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BOLD = "\033[1m"
    WHITE = "\033[97m"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        for attr in (
            "CYAN",
            "DIM",
            "GREEN",
            "RED",
            "YELLOW",
            "BOLD",
            "WHITE",
            "MAGENTA",
            "RESET",
        ):
            setattr(cls, attr, "")


_IS_TTY = sys.stdout.isatty()
# Respect NO_COLOR convention and disable in non-TTY
if not _IS_TTY or os.environ.get("NO_COLOR"):
    _C.disable()


# ── Spinner ──────────────────────────────────────────────────────

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_THINKING_PHRASES = [
    "Thinking…",
    "Reasoning…",
    "Analyzing…",
    "Considering…",
    "Evaluating…",
    "Postulating…",
    "Theorizing…",
    "Examining…",
]

_AGENT_ACTIVITY = {
    "project_builder": "Scoping project…",
    "planning_agent": "Designing method…",
    "task_agent": "Running experiment…",
    "evaluator": "Evaluating results…",
    "suggestion_agent": "Generating suggestions…",
    "tool_builder": "Building tool…",
    "literature_agent": "Searching knowledge…",
}


# ── Header ───────────────────────────────────────────────────────


def print_header(
    project_name: str = "",
    agent: str = "",
    mode: str = "",
    data_source: str = "",
) -> None:
    """Print branded Urika header box."""
    tagline = "  Multi-agent scientific analysis platform"
    lines = [tagline]
    if project_name:
        project_line = f"  Project: {project_name}"
        if mode:
            project_line += f" · {mode}"
        lines.append(project_line)
    if agent:
        lines.append(f"  Agent: {agent}")
    if data_source:
        short = data_source if len(data_source) <= 60 else "…" + data_source[-57:]
        lines.append(f"  Data: {short}")

    width = max(len(line) for line in lines) + 2
    bar = "─" * (width - len(" Urika "))

    print(f"\n{_C.CYAN}╭─ {_C.BOLD}Urika{_C.RESET}{_C.CYAN} {bar}╮{_C.RESET}")
    for line in lines:
        print(f"{_C.CYAN}│{_C.RESET}{line:<{width}}{_C.CYAN}│{_C.RESET}")
    print(f"{_C.CYAN}╰{'─' * width}╯{_C.RESET}")
    print()


# ── Footer ───────────────────────────────────────────────────────


def print_footer(
    duration_ms: int = 0,
    turns: int = 0,
    status: str = "",
    extra: str = "",
) -> None:
    """Print session footer with stats."""
    duration = _format_duration(duration_ms)
    parts = []
    if turns:
        parts.append(f"{turns} turns")
    parts.append(duration)
    if extra:
        parts.append(extra)

    print(f"\n{_C.DIM}{'─' * 44}{_C.RESET}")
    print(f"  {' · '.join(parts)}")
    if status == "completed":
        print(f"  {_C.GREEN}✓ Complete{_C.RESET}")
    elif status == "failed":
        print(f"  {_C.RED}✗ Failed{_C.RESET}")
    print()


# ── Inline activity ──────────────────────────────────────────────


def print_step(label: str, detail: str = "") -> None:
    """Print a step indicator."""
    if detail:
        print(f"  {_C.CYAN}▸{_C.RESET} {label} {_C.DIM}{detail}{_C.RESET}")
    else:
        print(f"  {_C.CYAN}▸{_C.RESET} {label}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"  {_C.GREEN}✓{_C.RESET} {msg}")


def print_error(msg: str) -> None:
    """Print an error message."""
    print(f"  {_C.RED}✗{_C.RESET} {msg}")


def print_warning(msg: str) -> None:
    """Print a warning message."""
    print(f"  {_C.YELLOW}!{_C.RESET} {msg}")


def print_agent(agent_name: str) -> None:
    """Print agent activity label."""
    activity = _AGENT_ACTIVITY.get(agent_name, f"Running {agent_name}…")
    print(f"\n  {_C.MAGENTA}◆{_C.RESET} {_C.BOLD}{activity}{_C.RESET}")


# ── Status bar ───────────────────────────────────────────────────


class StatusBar:
    """Persistent status bar pinned to terminal bottom via scroll region.

    Includes animated spinner showing current activity.
    """

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.project = ""
        self.agent = ""
        self.activity = ""
        self._active = False
        self._rows = 0
        self._cols = 0
        self._spin_idx = 0
        self._spin_task: asyncio.Task | None = None

    def activate(self) -> None:
        """Switch on scroll region. Call BEFORE any print() output."""
        if not _IS_TTY:
            return
        try:
            size = os.get_terminal_size()
            self._rows = size.lines
            self._cols = size.columns
        except OSError:
            return
        if self._rows < 10:
            return
        self._active = True
        sys.stdout.write(f"\033[2J\033[1;{self._rows - 2}r\033[H")
        sys.stdout.flush()

    def start_spinner(self) -> None:
        """Start background spinner animation task."""
        if not self._active or self._spin_task is not None:
            return
        self._spin_task = asyncio.create_task(self._spin_loop())

    async def _spin_loop(self) -> None:
        """Animate spinner at ~8 Hz."""
        try:
            while True:
                await asyncio.sleep(0.12)
                if self._active:
                    self._spin_idx = (self._spin_idx + 1) % len(_SPINNER)
                    self._render()
        except asyncio.CancelledError:
            pass

    def _render(self) -> None:
        """Draw status bar in the 2 reserved rows below scroll region."""
        if not self._active:
            return
        elapsed = _format_duration(int((time.monotonic() - self.start) * 1000))
        parts = [elapsed]
        if self.project:
            parts.append(self.project)
        if self.agent:
            parts.append(self.agent)
        status = " · ".join(parts)

        act = ""
        if self.activity:
            ch = _SPINNER[self._spin_idx]
            act = f"  {_C.CYAN}{ch}{_C.RESET} {_C.DIM}{self.activity}{_C.RESET}"

        buf = "\0337"
        buf += f"\033[{self._rows - 1};1H\033[K{_C.DIM}{'─' * self._cols}{_C.RESET}"
        buf += (
            f"\033[{self._rows};1H\033[K"
            f"  {_C.CYAN}▪{_C.RESET} {_C.DIM}{status}{_C.RESET}{act}"
        )
        buf += "\0338"
        sys.stdout.write(buf)
        sys.stdout.flush()

    def render(self) -> None:
        """Public render with spin index reset."""
        self._spin_idx = 0
        self._render()

    def update(self, **kw: str) -> None:
        """Update status bar fields and re-render."""
        for k, v in kw.items():
            if hasattr(self, k):
                setattr(self, k, v)
        self.render()

    def cleanup(self) -> None:
        """Reset scroll region and clear status rows."""
        if self._spin_task is not None:
            self._spin_task.cancel()
            self._spin_task = None
        if not self._active:
            return
        self._active = False
        sys.stdout.write(f"\033[{self._rows - 1};1H\033[K")
        sys.stdout.write(f"\033[{self._rows};1H\033[K")
        sys.stdout.write(f"\033[r\033[{self._rows - 2};1H")
        sys.stdout.flush()


# ── Sync spinner context manager ─────────────────────────────────


class Spinner:
    """Simple synchronous spinner for blocking operations.

    Usage:
        with Spinner("Scanning data files"):
            do_slow_thing()
    """

    def __init__(self, message: str) -> None:
        self.message = message
        self._active = False
        self._thread: object = None

    def __enter__(self) -> Spinner:
        if not _IS_TTY:
            print(f"  {self.message}")
            return self
        self._active = True
        # Print initial static message in case spinner thread doesn't start
        sys.stdout.write(f"  {_C.DIM}{self.message}{_C.RESET}")
        sys.stdout.flush()
        import threading

        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._active = False
        if self._thread is not None:
            self._thread.join(timeout=1)
        if _IS_TTY:
            # Clear spinner line and reset colors
            try:
                sys.stdout.write("\r\033[K\033[0m")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass

    def _spin(self) -> None:
        idx = 0
        while self._active:
            ch = _SPINNER[idx % len(_SPINNER)]
            try:
                sys.stdout.write(
                    f"\r  {_C.CYAN}{ch}{_C.RESET} {_C.DIM}{self.message}{_C.RESET}\033[K"
                )
                sys.stdout.flush()
            except (OSError, ValueError):
                break
            idx += 1
            time.sleep(0.12)


# ── Helpers ──────────────────────────────────────────────────────


def _format_duration(ms: int) -> str:
    """Format milliseconds as human-readable duration."""
    if ms < 1000:
        return f"{ms}ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f}s"
    m = int(s) // 60
    remaining_s = int(s) % 60
    return f"{m}m {remaining_s}s"


def thinking_phrase() -> str:
    """Return a random thinking phrase."""
    import random

    return random.choice(_THINKING_PHRASES)
