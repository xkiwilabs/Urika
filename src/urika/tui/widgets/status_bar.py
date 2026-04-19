"""Persistent 2-line status bar showing session state."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from urika.cli_display import _format_duration
from urika.repl.session import ReplSession


class StatusBar(Static):
    """Single-line status bar at the very bottom of the TUI.

    Shows: urika │ project │ model │ tokens · calls │ cost │ processing time

    Agent activity (spinner, verb, subagent name) is handled by
    ActivityBar above — NOT duplicated here.
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    # Trigger re-render on tick
    tick = reactive(0)

    def __init__(self, session: ReplSession, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render_line1(self) -> str:
        """Build line 1: urika · project · privacy · agent."""
        parts = ["urika"]
        if self.session.has_project:
            parts.append(self.session.project_name)
            # Privacy mode — failures here must not crash the render path,
            # but we narrow to I/O and parse errors only. AttributeError /
            # TypeError from a renamed session field should propagate so
            # bugs surface loudly in tests instead of silently blanking the
            # privacy badge forever.
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(self.session.project_path)
                if rc.privacy_mode != "open":
                    parts.append(rc.privacy_mode)
            except (OSError, ValueError, KeyError) as exc:
                self.log.warning(f"privacy-mode lookup failed: {exc}")
        if self.session.agent_running:
            parts.append(self.session.agent_name or "working")
            if self.session.agent_activity:
                parts.append(self.session.agent_activity)
        return " · ".join(parts)

    def render_line2(self) -> str:
        """Build line 2: model · tokens · cost · processing time."""
        parts: list[str] = []
        if self.session.model:
            parts.append(self.session.model)
        tokens = self.session.total_tokens_in + self.session.total_tokens_out
        if tokens > 0:
            tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
            parts.append(f"{tok_str} tokens")
        if self.session.total_cost_usd > 0:
            parts.append(f"~${self.session.total_cost_usd:.2f}")
        processing = _format_duration(self.session.processing_ms)
        parts.append(processing)
        return " · ".join(parts)

    def render(self) -> Text:
        """Single-line colored Rich Text.

        urika │ project │ model │ tokens · calls │ cost │ processing time

        Agent activity (spinner, verb) is handled by ActivityBar
        above — NOT shown here. Colors match the REPL/CLI palette.
        """
        URIKA = "bold #4a9eff"
        CYAN = "#00d7ff"
        GREEN = "#66ff99"
        MAGENTA = "#cc66ff"
        DIM = "#666666"

        sep = Text(" │ ", style=DIM)

        parts: list[Text] = [Text("urika", style=URIKA)]

        if self.session.has_project:
            parts.append(Text(self.session.project_name or "", style=CYAN))

        if self.session.model:
            parts.append(Text(self.session.model, style=CYAN))

        tokens = self.session.total_tokens_in + self.session.total_tokens_out
        tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
        parts.append(
            Text(f"{tok_str} tokens · {self.session.agent_calls} calls", style=DIM)
        )

        if self.session.total_cost_usd > 0:
            parts.append(Text(f"~${self.session.total_cost_usd:.2f}", style=GREEN))
        else:
            parts.append(Text("$0.00", style=DIM))

        processing = _format_duration(self.session.processing_ms)
        parts.append(Text(processing, style=MAGENTA))

        out = Text()
        for i, part in enumerate(parts):
            if i > 0:
                out.append(sep)
            out.append(part)
        return out

    def on_mount(self) -> None:
        """Start a 250ms timer to refresh status."""
        self.set_interval(0.25, self._refresh_tick)

    def _refresh_tick(self) -> None:
        """Bump tick to trigger re-render."""
        self.tick += 1

    def watch_tick(self, _value: int) -> None:
        """Re-render when tick changes."""
        self.refresh()
