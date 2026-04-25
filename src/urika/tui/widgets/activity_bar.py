"""Animated activity bar — shows what the system is doing.

Sits between the InputBar and StatusBar. When an agent is running it
shows a spinner + rotating verb (Thinking, Reasoning, Analyzing, ...)
so the TUI doesn't look static during long orchestrator calls.
When idle, shows a dim "ready" label.
"""

from __future__ import annotations

import random
import time

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from urika.cli_display import rich_color_for_command
from urika.repl.session import ReplSession

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_ACTIVITY_VERBS = [
    "Thinking",
    "Reasoning",
    "Analyzing",
    "Processing",
    "Exploring",
    "Evaluating",
    "Considering",
    "Reviewing",
]


class ActivityBar(Static):
    """Animated spinner + verb shown while an agent is working.

    Refreshes at 4 Hz (250 ms) via a timer started on mount. When
    ``session.agent_running`` is False a dim "ready" label is shown.
    When True it expands to show e.g.::

        ⠹ run — planning_agent — Thinking…

    The verb rotates at randomized intervals (3–8 s). If the
    session's ``agent_activity`` is set to a subagent name (e.g.
    "planning_agent"), it appears between the command and the verb.
    """

    DEFAULT_CSS = """
    ActivityBar {
        height: 1;
        padding: 0 1;
        color: #ffcc66;
        background: $surface;
    }
    """

    tick = reactive(0)

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._frame_idx = 0
        self._verb_idx = 0
        self._last_verb_change = 0.0
        self._next_verb_interval = random.uniform(3.0, 8.0)

    def on_mount(self) -> None:
        """Start the animation timer."""
        self.set_interval(0.25, self._tick)

    def _tick(self) -> None:
        self.tick += 1

    def watch_tick(self, _value: int) -> None:
        """Re-render on every tick."""
        self.refresh()

    def render(self) -> Text:
        if not self.session.agent_running:
            return Text(" ready", style="dim #666666")

        # Spinner frame
        frame = _SPINNER_FRAMES[self._frame_idx % len(_SPINNER_FRAMES)]
        self._frame_idx += 1

        # Command name (e.g. "run", "new", "finalize")
        cmd_name = self.session.agent_name or self.session.active_command or "agent"

        # Subagent — agent_activity is set to the current subagent key
        # (e.g. "planning_agent", "evaluator") by the orchestrator's
        # progress callback. Generic values are not subagents.
        subagent = self.session.agent_activity
        _generic = {"", "Working…"}
        is_subagent = subagent and subagent not in _generic

        # Verb — rotate through generic verbs at randomized intervals
        now = time.monotonic()
        if now - self._last_verb_change > self._next_verb_interval:
            self._verb_idx = (self._verb_idx + 1) % len(_ACTIVITY_VERBS)
            self._last_verb_change = now
            self._next_verb_interval = random.uniform(3.0, 8.0)
        verb = _ACTIVITY_VERBS[self._verb_idx]

        # Per-command / per-subagent colours — same palette as the CLI
        # so users see one colour language across all three surfaces.
        cmd_style = f"bold {rich_color_for_command(cmd_name)}"
        text = Text()
        text.append(f" {frame} ", style="bold #4a9eff")
        text.append(cmd_name, style=cmd_style)
        if is_subagent:
            sub_style = rich_color_for_command(subagent)
            text.append(" — ", style="dim")
            text.append(subagent, style=sub_style)
        text.append(f" — {verb}…", style="dim")
        return text
