"""Scrollable output panel for agent output."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog


class OutputPanel(RichLog):
    """Scrollable panel that displays all agent output.

    Wraps RichLog with auto-scroll behavior: scrolls to bottom on new
    content unless the user has scrolled up manually.
    """

    DEFAULT_CSS = """
    OutputPanel {
        height: 1fr;
        border-bottom: solid $accent;
    }
    """

    @property
    def line_count(self) -> int:
        """Return the number of lines written so far."""
        return len(self.lines)

    def write_line(self, content: str | Text) -> None:
        """Write a line to the output panel."""
        self.write(content)
