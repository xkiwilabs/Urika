"""Persistent 2-line status bar showing session state."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from urika.cli_display import _format_duration
from urika.repl_session import ReplSession


class StatusBar(Static):
    """Two-line status bar pinned to the bottom of the TUI.

    Line 1: urika · project · privacy · active-agent
    Line 2: model · tokens · cost · elapsed
    """

    DEFAULT_CSS = ""

    tick = reactive(0)

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render_line1(self) -> str:
        """Build line 1: urika · project · privacy · agent."""
        parts = ["urika"]
        if self.session.has_project:
            parts.append(self.session.project_name)
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(self.session.project_path)
                if rc.privacy_mode != "open":
                    parts.append(rc.privacy_mode)
            except Exception:
                pass
        if self.session.agent_running:
            parts.append(self.session.agent_name or "working")
            if self.session.agent_activity:
                parts.append(self.session.agent_activity)
        return " · ".join(parts)

    def render_line2(self) -> str:
        """Build line 2: model · tokens · cost · elapsed."""
        parts = []
        if self.session.model:
            parts.append(self.session.model)
        tokens = self.session.total_tokens_in + self.session.total_tokens_out
        if tokens > 0:
            tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
            parts.append(f"{tok_str} tokens")
        if self.session.total_cost_usd > 0:
            parts.append(f"~${self.session.total_cost_usd:.2f}")
        elapsed = _format_duration(self.session.elapsed_ms)
        parts.append(elapsed)
        return " · ".join(parts)

    def render(self) -> Text:
        """Render both lines."""
        line1 = self.render_line1()
        line2 = self.render_line2()
        text = Text()
        text.append(line1 + "\n")
        text.append(line2, style="dim")
        return text

    def on_mount(self) -> None:
        """Start a 250ms timer to refresh status."""
        self.set_interval(0.25, self._refresh_tick)

    def _refresh_tick(self) -> None:
        """Bump tick to trigger re-render."""
        self.tick += 1

    def watch_tick(self, _value: int) -> None:
        """Re-render when tick changes."""
        self.refresh()
