"""Animated activity bar — shows what the system is doing.

Sits between the InputBar and StatusBar. When an agent is running it
shows a spinner + rotating verb (Thinking, Reasoning, Analyzing, ...)
so the TUI doesn't look static during long orchestrator calls.
When idle, the widget is invisible (height 0).
"""

from __future__ import annotations

import time

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

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
    ``session.agent_running`` is False the widget collapses to zero
    height so it takes no screen space when idle. When True it
    expands to one row and shows e.g.::

        ⠹ chat — Thinking…

    The verb rotates every 5 seconds. If the session's
    ``agent_activity`` is set (e.g. "Reading progress.json"), it
    replaces the generic verb — this lets subagents describe their
    actual work.
    """

    DEFAULT_CSS = """
    ActivityBar {
        height: 1;
        padding: 0 1;
        color: #ffcc66;
    }
    """

    tick = reactive(0)

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._frame_idx = 0
        self._verb_idx = 0
        self._last_verb_change = 0.0

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

        # Agent name
        agent_name = self.session.agent_name or self.session.active_command or "agent"

        # Verb — use agent_activity if set, otherwise rotate generics
        activity = self.session.agent_activity
        if not activity or activity == "Working…":
            now = time.monotonic()
            if now - self._last_verb_change > 5.0:
                self._verb_idx = (self._verb_idx + 1) % len(_ACTIVITY_VERBS)
                self._last_verb_change = now
            activity = _ACTIVITY_VERBS[self._verb_idx]

        text = Text()
        text.append(f" {frame} ", style="bold #4a9eff")
        text.append(agent_name, style="bold #ffcc66")
        text.append(f" — {activity}…", style="dim")
        return text
