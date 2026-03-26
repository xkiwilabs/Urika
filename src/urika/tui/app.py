"""Main Textual application for Urika."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
