"""Terminal display for Urika CLI — colors, agent labels, spinners, thinking panel.

Pure ANSI escape sequences, no external dependencies.
Gracefully degrades when stdout is not a TTY.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
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


# ── Color system ─────────────────────────────────────────────────


class _C:
    """ANSI color codes."""

    # Urika brand
    BLUE = "\033[34m"
    # Agent colors
    CYAN = "\033[36m"  # planning_agent, tool_builder
    GREEN = "\033[32m"  # task_agent, success
    YELLOW = "\033[33m"  # evaluator, warnings
    MAGENTA = "\033[35m"  # advisor_agent
    RED = "\033[31m"  # errors
    # Modifiers
    BOLD = "\033[1m"
    DIM = "\033[2m"
    WHITE = "\033[97m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        for attr in (
            "BLUE",
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
# Colors on by default for TTYs. Disable via NO_COLOR=1.
if not _IS_TTY or os.environ.get("NO_COLOR"):
    _C.disable()


# ── Agent color map ──────────────────────────────────────────────

_AGENT_COLORS: dict[str, str] = {
    "project_builder": _C.BLUE,
    "planning_agent": _C.CYAN,
    "task_agent": _C.GREEN,
    "evaluator": _C.YELLOW,
    "advisor_agent": _C.MAGENTA,
    "tool_builder": _C.CYAN + _C.DIM,
    "literature_agent": _C.BLUE + _C.DIM,
    "report_agent": _C.BLUE,
    "presentation_agent": _C.BLUE + _C.DIM,
}

_AGENT_LABELS: dict[str, str] = {
    "project_builder": "Project Builder",
    "planning_agent": "Planning Agent",
    "task_agent": "Task Agent",
    "evaluator": "Evaluator",
    "advisor_agent": "Advisor Agent",
    "tool_builder": "Tool Builder",
    "literature_agent": "Literature Agent",
    "report_agent": "Report Agent",
    "presentation_agent": "Presentation Agent",
}


# ── Spinner frames ───────────────────────────────────────────────

_SPINNER = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"

_THINKING_PHRASES = [
    "Thinking\u2026",
    "Reasoning\u2026",
    "Analyzing\u2026",
    "Considering\u2026",
    "Evaluating\u2026",
    "Postulating\u2026",
    "Theorizing\u2026",
    "Examining\u2026",
]

_AGENT_ACTIVITY: dict[str, str] = {
    "project_builder": "Scoping project\u2026",
    "planning_agent": "Designing method\u2026",
    "task_agent": "Running experiment\u2026",
    "evaluator": "Evaluating results\u2026",
    "advisor_agent": "Generating suggestions\u2026",
    "tool_builder": "Building tool\u2026",
    "literature_agent": "Searching knowledge\u2026",
    "report_agent": "Writing report\u2026",
    "presentation_agent": "Creating slides\u2026",
    "finalizer": "Finalizing project\u2026",
}


# ── Header ───────────────────────────────────────────────────────


def print_header(
    project_name: str = "",
    agent: str = "",
    mode: str = "",
    data_source: str = "",
) -> None:
    """Print branded Urika header banner with discovery icon."""
    # Build right-side content
    info_parts = []
    if project_name:
        p = project_name
        if mode:
            p += f" · {mode}"
        info_parts.append(p)
    if agent:
        info_parts.append(agent)
    if data_source:
        short = data_source if len(data_source) <= 50 else "…" + data_source[-47:]
        info_parts.append(short)
    info = ("  " + " │ ".join(info_parts)) if info_parts else ""

    # Banner width — capped at 76
    min_width = 72
    max_width = 76
    content_width = min(max_width, max(min_width, len(info) + 20))
    bar_top = "─" * (content_width - len(" Urika v0.1 "))
    bar_bot = "─" * content_width

    B = _C.BLUE
    R = _C.RESET
    D = _C.DIM
    BO = _C.BOLD

    # Truncate info to fit
    max_info = content_width - 7
    if len(info) > max_info:
        info = info[: max_info - 1] + "…"

    w = content_width  # visible character width
    ver = "Version: 0.1.0        Release: 2026-03-21"

    def _pad(text: str, visible_len: int) -> str:
        """Pad to fill the box width, accounting for visible chars only."""
        return " " * (w - visible_len)

    # ASCII art logo + double border
    logo = [
        "██╗   ██╗██████╗ ██╗██╗  ██╗ █████╗ ",
        "██║   ██║██╔══██╗██║██║ ██╔╝██╔══██╗",
        "██║   ██║██████╔╝██║█████╔╝ ███████║",
        "██║   ██║██╔══██╗██║██╔═██╗ ██╔══██║",
        "╚██████╔╝██║  ██║██║██║  ██╗██║  ██║",
        " ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝",
    ]
    logo_width = max(len(line) for line in logo)

    # Recalculate width to fit logo
    w = max(w, logo_width + 4)
    bar_top = "─" * (w - len(" v0.1 "))
    bar_bot = "─" * w

    def _center(text: str, icon: str = "") -> tuple[str, str]:
        """Return left padding and right padding to center text in box."""
        visible = len(icon) + (1 if icon else 0) + len(text)
        total_pad = w - visible
        left = total_pad // 2
        right = total_pad - left
        return " " * left, " " * right

    print(f"\n{B}╭─ v0.1 {bar_top}╮╮{R}")
    print(f"{B}│{R}{' ' * w}{B}││{R}")
    for line in logo:
        total_pad = w - len(line)
        left = total_pad // 2
        right = total_pad - left
        print(f"{B}│{R}{' ' * left}{B}{line}{R}{' ' * right}{B}││{R}")
    print(f"{B}│{R}{' ' * w}{B}││{R}")

    t1 = "Multi-agent scientific analysis platform"
    l1, r1 = _center(t1, "✦")
    print(f"{B}│{R}{l1}{B}✦{R} {BO}{t1}{R}{r1}{B}││{R}")

    t2 = "Autonomous exploration · analysis · modelling · evaluation"
    l2, r2 = _center(t2, "◆")
    print(f"{B}│{R}{l2}{B}◆{R} {D}{t2}{R}{r2}{B}││{R}")

    t3 = ver
    l3, r3 = _center(t3, "✦")
    print(f"{B}│{R}{l3}{B}✦{R} {D}{t3}{R}{r3}{B}││{R}")

    if info:
        print(f"{B}│{R}{' ' * w}{B}││{R}")
        vis_len = len(info.replace("│", "|"))
        pad = " " * max(0, w - vis_len)
        print(f"{B}│{R}{info}{pad}{B}││{R}")

    print(f"{B}│{R}{' ' * w}{B}││{R}")
    print(f"{B}╰{bar_bot}╯│{R}")
    print(f" {B}╰{bar_bot}╯{R}")
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

    rule = "\u2500" * 44
    sep = " \u00b7 ".join(parts)
    print(f"\n{_C.DIM}{rule}{_C.RESET}")
    print(f"  {sep}")
    if status == "completed":
        print(f"  {_C.GREEN}\u2713 Complete{_C.RESET}")
    elif status == "failed":
        print(f"  {_C.RED}\u2717 Failed{_C.RESET}")
    print()


# ── Inline activity ──────────────────────────────────────────────


def print_step(label: str, detail: str = "") -> None:
    """Print a step indicator."""
    if detail:
        print(f"  {_C.CYAN}\u25b8{_C.RESET} {label} {_C.DIM}{detail}{_C.RESET}")
    else:
        print(f"  {_C.CYAN}\u25b8{_C.RESET} {label}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"  {_C.GREEN}\u2713{_C.RESET} {msg}")


def print_error(msg: str) -> None:
    """Print an error message."""
    print(f"  {_C.RED}\u2717{_C.RESET} {msg}")


def print_warning(msg: str) -> None:
    """Print a warning message."""
    print(f"  {_C.YELLOW}!{_C.RESET} {msg}")


def print_agent(agent_name: str) -> None:
    """Print agent activity label with colored separator line."""
    color = _AGENT_COLORS.get(agent_name, _C.BLUE)
    label = _AGENT_LABELS.get(agent_name, agent_name)
    print(
        f"\n  {color}\u2500\u2500\u2500 {label}"
        f" \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        f"\u2500\u2500\u2500\u2500{_C.RESET}"
    )


# ── Verbose tool output ─────────────────────────────────────────


def print_tool_use(tool_name: str, detail: str = "") -> None:
    """Print a tool use event (for verbose mode)."""
    tool_colors: dict[str, str] = {
        "Bash": _C.YELLOW,
        "Write": _C.GREEN,
        "Edit": _C.GREEN,
        "Read": _C.DIM,
        "Glob": _C.DIM,
        "Grep": _C.DIM,
    }
    color = tool_colors.get(tool_name, _C.DIM)
    icon = "\u25b8"
    short = detail[:100] + "..." if len(detail) > 100 else detail
    print(f"    {color}{icon} {tool_name}{_C.RESET} {_C.DIM}{short}{_C.RESET}")


# ── Thinking panel (scroll-region status bar) ────────────────────


_TOOL_VERBS: dict[str, str] = {
    "Bash": "Running…",
    "Write": "Writing…",
    "Edit": "Editing…",
    "Read": "Reading…",
    "Glob": "Searching…",
    "Grep": "Searching…",
    "TodoWrite": "Planning…",
}


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
        self.activity = "Thinking…"
        self._active = False
        self._rows = 0
        self._cols = 0
        self._spin_idx = 0
        self._lock = threading.Lock()
        self._spin_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def activate(self) -> None:
        """Set up scroll region, reserving 3 bottom lines.

        Call BEFORE any print() output. Becomes a no-op if terminal is
        too small (< 10 rows) or not a TTY.
        """
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
        try:
            self._active = True
            # Set scroll region without clearing screen (preserves scroll history)
            sys.stdout.write(f"\033[1;{self._rows - 3}r\033[{self._rows - 4};1H")
            sys.stdout.flush()
            atexit.register(self.cleanup)
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
                    self._render()

    def _render(self) -> None:
        """Draw the 2 reserved rows below the scroll region.

        Line 1: empty padding
        Line 2: spinner + agent + verb ... project + model + elapsed

        Must be called with self._lock held or from a safe context.
        """
        if not self._active:
            return
        try:
            elapsed = _format_duration(int((time.monotonic() - self.start) * 1000))

            # Left side: spinner + agent + activity verb (blue)
            ch = _SPINNER[self._spin_idx]
            agent_color = _AGENT_COLORS.get(self.agent, _C.BLUE)
            agent_label = _AGENT_LABELS.get(self.agent, self.agent)
            left = (
                f"  {_C.BLUE}{ch}{_C.RESET}"
                f" {agent_color}{agent_label}{_C.RESET}"
                f" {_C.BLUE}· {self.activity}{_C.RESET}"
            )

            # Right side: project (dim) + model (cyan) + elapsed (red)
            right_parts = []
            if self.project:
                right_parts.append(f"{_C.DIM}{self.project}{_C.RESET}")
            if self.model:
                right_parts.append(f"{_C.CYAN}{self.model}{_C.RESET}")
            right_parts.append(f"{_C.RED}{elapsed}{_C.RESET}")
            right = f" {_C.DIM}·{_C.RESET} ".join(right_parts)

            sep = "\u2500" * self._cols
            buf = "\0337"  # save cursor
            # Line 1: separator
            buf += f"\033[{self._rows - 2};1H\033[K{_C.DIM}{sep}{_C.RESET}"
            # Line 2: status line
            buf += f"\033[{self._rows - 1};1H\033[K{left}  {right}"
            # Line 3: empty padding
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
            if model:
                self.model = model
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
            # Shorten model name
            short = model
            if "/" in short:
                short = short.split("/")[-1]
            if len(short) > 25:
                short = short[:22] + "…"
            self.model = short
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
            # Clear the 3 reserved lines
            sys.stdout.write(f"\033[{self._rows - 2};1H\033[K")
            sys.stdout.write(f"\033[{self._rows - 1};1H\033[K")
            sys.stdout.write(f"\033[{self._rows};1H\033[K")
            # Restore full scroll region and position cursor
            sys.stdout.write(f"\033[r\033[{self._rows - 3};1H")
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
        if not _IS_TTY:
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
        if _IS_TTY:
            try:
                sys.stdout.write("\r\033[K\033[0m")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass

    def update(self, message: str) -> None:
        """Update the spinner message."""
        if self._lock is not None:
            self._lock.acquire()
        self.message = message
        if self._lock is not None:
            self._lock.release()

    def update_session(self, **kwargs: object) -> None:
        """Update session info fields and re-render on the next tick.

        Accepted keyword arguments: ``model``, ``cost``, ``project``.
        """
        if self._lock is not None:
            self._lock.acquire()
        try:
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
        finally:
            if self._lock is not None:
                self._lock.release()

    def print_above(self, text: str) -> None:
        """Print a line above the spinner, keeping the spinner on the last line."""
        if not _IS_TTY:
            print(text)
            return
        if self._lock is not None:
            self._lock.acquire()
        try:
            sys.stdout.write(f"\r\033[K{text}\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        finally:
            if self._lock is not None:
                self._lock.release()

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
                self._lock.acquire()
            msg = self.message
            right_info = (
                self._build_right_info() if self._project or self._model else ""
            )
            if self._lock is not None:
                self._lock.release()
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
