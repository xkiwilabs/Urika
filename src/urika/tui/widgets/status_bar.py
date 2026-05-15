"""Single-line status bar showing session state."""

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

    def render(self) -> Text:
        """Single-line colored Rich Text.

        urika │ project │ privacy │ model │ tokens · calls │ cost │ processing time

        Agent activity (spinner, verb) is handled by ActivityBar
        above — NOT shown here. Colors match the REPL/CLI palette.
        """
        URIKA = "bold #4a9eff"
        CYAN = "#00d7ff"
        GREEN = "#66ff99"
        MAGENTA = "#cc66ff"
        YELLOW = "#ffcc00"
        RED = "bold #ff4444"
        DIM = "#666666"

        sep = Text(" │ ", style=DIM)

        parts: list[Text] = [Text("urika", style=URIKA)]

        if self.session.has_project:
            parts.append(Text(self.session.project_name or "", style=CYAN))

            # Privacy mode + broken-endpoint warning. private/hybrid
            # without a usable endpoint paint red so the user notices
            # before the next agent run hard-fails.
            mode, broken = self._privacy_state()
            if broken:
                parts.append(Text(f"{mode} ⚠ no endpoint", style=RED))
            else:
                parts.append(Text(mode, style=YELLOW))

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

    def _privacy_state(self) -> tuple[str, bool]:
        """Return ``(mode, broken)`` for the current project.

        ``broken`` is True when mode is private/hybrid and no usable
        private endpoint is configured (project-local or globally).
        Cached on the widget per project_path so we don't reload the
        runtime config on every 250ms tick.
        """
        if not self.session.has_project or not self.session.project_path:
            return ("open", False)
        cache = getattr(self, "_privacy_cache", None)
        if cache is None:
            cache = {}
            self._privacy_cache = cache
        key = str(self.session.project_path)
        if key in cache:
            return cache[key]
        try:
            from urika.agents.config import load_runtime_config

            rc = load_runtime_config(self.session.project_path)
            mode = rc.privacy_mode
            broken = False
            if mode in ("private", "hybrid"):
                broken = not any(
                    (ep.base_url or "").strip() for ep in rc.endpoints.values()
                )
            cache[key] = (mode, broken)
        except Exception:
            cache[key] = ("open", False)
        return cache[key]
