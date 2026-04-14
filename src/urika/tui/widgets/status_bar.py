"""Persistent 2-line status bar showing session state."""

from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from urika.cli_display import _format_duration
from urika.repl.session import ReplSession


class StatusBar(Static):
    """Two-line status bar pinned to the bottom of the TUI.

    Line 1: urika · project · privacy · active-agent
    Line 2: model · tokens · cost · elapsed
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 2;
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
        """Build line 2: model · tokens · cost · elapsed."""
        parts: list[str] = []
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
        """Render both lines as a colored Rich Text.

        Matches the REPL/CLI footer palette so the TUI's status bar
        is visually consistent with the classic interface. Field
        colors (mapping the original ANSI codes):

          urika       bold #4a9eff (Urika blue, same as the banner)
          project     cyan
          privacy     yellow
          agent name  yellow (only while agent_running)
          activity    dim (only while agent_running)
          model       cyan
          elapsed     magenta
          tokens/calls dim
          cost        green if > 0, else dim

        Separator is ``│`` in dim grey — matching the REPL toolbar.
        We build the Rich Text directly here rather than reusing
        the plain-string helpers because the tests depend on those
        returning plain strings (see test_status_bar.py).
        """
        # Hex values chosen to look right against Textual's default
        # dark theme surface color. The "urika" label matches the
        # banner hex exactly for brand consistency.
        URIKA = "bold #4a9eff"
        CYAN = "#00d7ff"
        YELLOW = "#ffcc66"
        MAGENTA = "#cc66ff"
        GREEN = "#66ff99"
        DIM = "#666666"

        sep = Text(" │ ", style=DIM)

        def _join(parts: list[Text]) -> Text:
            """Join parts with the dim separator."""
            joined = Text()
            for i, part in enumerate(parts):
                if i > 0:
                    joined.append(sep)
                joined.append(part)
            return joined

        # ── Line 1: urika · project · privacy · agent ──
        line1_parts: list[Text] = [Text("urika", style=URIKA)]
        if self.session.has_project:
            line1_parts.append(Text(self.session.project_name or "", style=CYAN))
            # Privacy badge lookup — same narrow exception policy
            # as the plain-string render_line1. Don't crash the
            # status bar render on a transient I/O error, but don't
            # silently swallow programmer bugs either.
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(self.session.project_path)
                if rc.privacy_mode != "open":
                    line1_parts.append(Text(rc.privacy_mode, style=YELLOW))
            except (OSError, ValueError, KeyError) as exc:
                self.log.warning(f"privacy-mode lookup failed: {exc}")
        if self.session.agent_running:
            line1_parts.append(
                Text(self.session.agent_name or "working", style=YELLOW)
            )
            if self.session.agent_activity:
                line1_parts.append(
                    Text(self.session.agent_activity, style=DIM)
                )

        # ── Line 2: model · elapsed · tokens · cost ──
        line2_parts: list[Text] = []
        if self.session.model:
            line2_parts.append(Text(self.session.model, style=CYAN))

        elapsed = _format_duration(self.session.elapsed_ms)
        line2_parts.append(Text(elapsed, style=MAGENTA))

        tokens = self.session.total_tokens_in + self.session.total_tokens_out
        tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
        line2_parts.append(
            Text(f"{tok_str} tokens · {self.session.agent_calls} calls", style=DIM)
        )

        if self.session.total_cost_usd > 0:
            line2_parts.append(
                Text(f"~${self.session.total_cost_usd:.2f}", style=GREEN)
            )
        else:
            line2_parts.append(Text("$0.00", style=DIM))

        out = Text()
        out.append(_join(line1_parts))
        out.append("\n")
        out.append(_join(line2_parts))
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
