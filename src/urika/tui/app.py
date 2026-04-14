"""Main Textual application for Urika."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.repl.session import ReplSession
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    def __init__(self, session: ReplSession | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session or ReplSession()

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield StatusBar(self.session)
        yield Footer()
