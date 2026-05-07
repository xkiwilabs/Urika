"""Terminal display for Urika CLI — colors, agent labels, spinners, thinking panel.

Pure ANSI escape sequences, no external dependencies.
Gracefully degrades when stdout is not a TTY.
"""

from __future__ import annotations

import atexit
import os
import sys


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
    ORANGE = "\033[38;5;208m"  # 256-color orange for experiment info
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
            "ORANGE",
            "RED",
            "YELLOW",
            "BOLD",
            "WHITE",
            "MAGENTA",
            "RESET",
        ):
            setattr(cls, attr, "")


# Pre-v0.4.2 ``_IS_TTY`` was evaluated at import time and frozen for
# the lifetime of the process — but Textual's TUI swaps ``sys.stdout``
# *after* import, and capture/release in tests can flip TTY status
# back and forth. The frozen flag turned spinners into permanent no-ops
# in those cases. ``_is_tty()`` re-checks at call time so display
# behaviour follows the current stdout. The module-level ``_IS_TTY``
# constant is kept as a backwards-compat alias for callers that read
# it directly; new code should call ``_is_tty()`` instead.


def _is_tty() -> bool:
    """Return True iff ``sys.stdout`` is currently a TTY.

    Re-evaluates on every call. Override the result for tests by
    patching ``sys.stdout.isatty`` (or via the standard ``capsys``
    capture which makes isatty return False).
    """
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        # AttributeError: stdout has no isatty (custom redirect).
        # ValueError: stdout closed mid-call.
        return False


_IS_TTY = _is_tty()  # back-compat alias; do not rely on freshness.

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
    "tool_builder": _C.ORANGE,
    "literature_agent": _C.BLUE + _C.BOLD,
    "report_agent": _C.WHITE,
    "presentation_agent": _C.GREEN + _C.BOLD,
    "data_agent": _C.CYAN + _C.BOLD,
    "finalizer": _C.MAGENTA + _C.BOLD,
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
    "data_agent": "Data Agent",
    "finalizer": "Finalizer",
}


# Rich-flavour version of _AGENT_COLORS for the TUI — same hue per agent
# as the CLI's ANSI palette, expressed as Rich style strings. Kept in
# lockstep with _AGENT_COLORS so the user sees one project-wide colour
# language whether they're in the CLI, classic REPL, or Textual TUI.
_AGENT_COLORS_RICH: dict[str, str] = {
    "project_builder": "#5b9bd5",            # blue
    "planning_agent": "#33b9b9",             # cyan
    "task_agent": "#5cb85c",                 # green
    "evaluator": "#ffcc66",                  # yellow
    "advisor_agent": "#cc99ff",              # magenta
    "tool_builder": "#ff8c42",               # orange
    "literature_agent": "bold #5b9bd5",
    "report_agent": "#dddddd",
    "presentation_agent": "bold #5cb85c",
    "data_agent": "bold #33b9b9",
    "finalizer": "bold #cc99ff",
}

# Top-level commands map to a primary agent for colouring purposes.
# The "run" loop touches several agents; we colour it as planning since
# planning kicks each turn off. Unknown commands fall back to brand blue.
_COMMAND_COLORS_RICH: dict[str, str] = {
    "run": "#33b9b9",                        # planning_agent (cyan)
    "finalize": "bold #cc99ff",              # finalizer
    "new": "#5b9bd5",                        # project_builder
    "advisor": "#cc99ff",                    # advisor_agent
    "evaluate": "#ffcc66",                   # evaluator
    "plan": "#33b9b9",                       # planning_agent
    "report": "#dddddd",                     # report_agent
    "present": "bold #5cb85c",               # presentation_agent
    "build-tool": "#ff8c42",                 # tool_builder
    "summarize": "#dddddd",                  # report_agent
}

_BRAND_COLOR_RICH = "#4a9eff"


def rich_color_for_command(name: str) -> str:
    """Return a Rich style string for a command or agent name.

    Looks up agents first (so subagent names like ``evaluator`` resolve
    correctly even when used as a command via ``urika evaluate``), then
    commands, then falls back to brand blue.
    """
    if name in _AGENT_COLORS_RICH:
        return _AGENT_COLORS_RICH[name]
    if name in _COMMAND_COLORS_RICH:
        return _COMMAND_COLORS_RICH[name]
    return _BRAND_COLOR_RICH


# ── Spinner frames ───────────────────────────────────────────────

_SPINNER = "\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f"  # braille dots

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

    B = _C.BLUE
    R = _C.RESET
    D = _C.DIM
    BO = _C.BOLD

    # Truncate info to fit
    max_info = content_width - 7
    if len(info) > max_info:
        info = info[: max_info - 1] + "…"

    w = content_width  # visible character width
    try:
        from importlib.metadata import version as _pkg_version

        _ver = _pkg_version("urika")
    except Exception:
        _ver = "0.0.0"
    ver = f"Version: {_ver}"
    v_label = f"v{_ver}"

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
    bar_top = "─" * (w - len(f" {v_label} "))
    bar_bot = "─" * w

    def _center(text: str, icon: str = "") -> tuple[str, str]:
        """Return left padding and right padding to center text in box."""
        visible = len(icon) + (1 if icon else 0) + len(text)
        total_pad = w - visible
        left = total_pad // 2
        right = total_pad - left
        return " " * left, " " * right

    print(f"\n{B}╭─ {v_label} {bar_top}╮╮{R}")
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


def format_agent_output(text: str) -> str:
    """Format agent output for terminal display.

    Finds JSON code blocks (```json ... ```) in the text, replaces them
    with a human-readable summary, and preserves all surrounding prose.
    """
    import json as _json
    import re

    if not text:
        return ""

    text = text.strip()

    def _format_json_block(match: re.Match) -> str:  # type: ignore[type-arg]
        raw = match.group(1).strip()
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError):
            return ""  # unparseable — drop silently

        if not isinstance(data, dict):
            return ""

        # -- Advisor suggestions --
        if "suggestions" in data:
            lines = [f"\n  {_C.BOLD}Suggested experiments:{_C.RESET}"]
            for i, s in enumerate(data["suggestions"], 1):
                name = s.get("name", f"exp-{i:03d}")
                method = s.get("method", s.get("description", ""))
                # Truncate long method descriptions to first sentence
                if method and len(method) > 120:
                    first_sentence = method.split(". ")[0].rstrip(".")
                    method = first_sentence[:120] + "…"
                lines.append(
                    f"    {_C.CYAN}{i}.{_C.RESET} {_C.BOLD}{name}{_C.RESET}"
                    f" {_C.DIM}— {method}{_C.RESET}"
                )
            cu = data.get("criteria_update")
            if cu and isinstance(cu, dict):
                rationale = cu.get("rationale", "")
                first_sentence = (
                    rationale.split(".")[0].strip() + "." if rationale else ""
                )
                if first_sentence and first_sentence != ".":
                    lines.append(
                        f"  {_C.YELLOW}Criteria update proposed:{_C.RESET} {first_sentence}"
                    )
            return "\n".join(lines)

        # -- Method plan --
        if "method_name" in data and "steps" in data:
            name = data["method_name"]
            lines = [f"\n  {_C.BOLD}Method:{_C.RESET} {_C.CYAN}{name}{_C.RESET}"]
            lines.append(f"  {_C.BOLD}Steps:{_C.RESET}")
            for i, step in enumerate(data["steps"], 1):
                desc = (
                    step
                    if isinstance(step, str)
                    else step.get("action", step.get("description", str(step)))
                )
                if len(desc) > 100:
                    desc = desc[:100] + "…"
                lines.append(f"    {_C.GREEN}{i}.{_C.RESET} {desc}")
            evaluation = data.get("evaluation", {})
            if evaluation:
                if isinstance(evaluation, dict):
                    strategy = evaluation.get("strategy", "")
                    metrics = evaluation.get("metrics", "")
                    if strategy or metrics:
                        parts = [p for p in [strategy, metrics] if p]
                        lines.append(
                            f"  {_C.BOLD}Evaluation:{_C.RESET} {' — '.join(parts)}"
                        )
                elif isinstance(evaluation, str):
                    lines.append(f"  {_C.BOLD}Evaluation:{_C.RESET} {evaluation}")
            return "\n".join(lines)

        # -- Evaluation result --
        if "criteria_met" in data:
            met = data["criteria_met"]
            met_str = f"{_C.GREEN}Yes{_C.RESET}" if met else f"{_C.YELLOW}No{_C.RESET}"
            lines = [f"\n  {_C.BOLD}Criteria met:{_C.RESET} {met_str}"]
            summary = data.get("summary", "")
            if summary:
                lines.append(f"  {_C.BOLD}Summary:{_C.RESET} {summary}")
            recs = data.get("recommendations", [])
            if recs:
                lines.append(f"  {_C.BOLD}Recommendations:{_C.RESET}")
                for r in recs:
                    lines.append(f"    {_C.DIM}\u2022{_C.RESET} {r}")
            return "\n".join(lines)

        # -- Unknown structure — drop the JSON block --
        return ""

    result = re.sub(
        r"```json\s*\n(.*?)\n\s*```",
        _format_json_block,
        text,
        flags=re.DOTALL,
    )

    # Clean up excessive blank lines left by removed blocks
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return f"\n{result}\n" if result else ""


def format_model_source(
    model: str,
    project_dir: object = None,
    agent_name: str = "",
) -> str:
    """Format model name with its endpoint source for display.

    Returns strings like:
        claude-sonnet-4-5           (open/default)
        ollama · qwen3:14b          (local Ollama)
        lm-studio · mistral-7b      (local LM Studio)
        institutional · claude-sonnet  (custom server endpoint)
    """
    if not model:
        return ""

    # Shorten model name
    short = model
    if "/" in short:
        short = short.split("/")[-1]
    if len(short) > 25:
        short = short[:22] + "\u2026"

    if project_dir is None:
        return short

    try:
        from pathlib import Path

        from urika.agents.config import load_runtime_config

        rc = load_runtime_config(Path(str(project_dir)))

        # Find which endpoint this agent/model uses
        endpoint_name = "open"
        if agent_name and agent_name in rc.model_overrides:
            endpoint_name = rc.model_overrides[agent_name].endpoint
        elif rc.privacy_mode == "private":
            endpoint_name = "private"
        elif rc.privacy_mode == "hybrid":
            _PRIVATE_AGENTS = {"data_agent", "tool_builder"}
            if agent_name in _PRIVATE_AGENTS:
                endpoint_name = "private"

        if endpoint_name == "open":
            return short

        endpoint = rc.endpoints.get(endpoint_name)
        if endpoint is None:
            return short

        url = endpoint.base_url.lower()
        if ":11434" in url:
            return f"ollama \u00b7 {short}"
        if ":1234" in url:
            return f"lm-studio \u00b7 {short}"
        if ":4200" in url:
            return f"vllm \u00b7 {short}"
        if "localhost" in url or "127.0.0.1" in url:
            return f"local \u00b7 {short}"
        # Remote custom endpoint
        return f"private-server \u00b7 {short}"
    except Exception:
        return short


# ── Re-exports from cli_display_panels (Phase 8 split) ────────────
# ThinkingPanel and Spinner moved out to keep this file focused on
# print/format helpers. Re-exported so existing imports keep working.
from urika.cli_display_panels import ThinkingPanel, Spinner  # noqa: E402, F401
