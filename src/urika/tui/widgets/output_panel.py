"""Scrollable output panel for agent output."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog


class OutputPanel(RichLog):
    """Scrollable panel that displays all agent output.

    Wraps RichLog with auto-scroll behavior: scrolls to bottom on new
    content unless the user has scrolled up manually.

    ``can_focus = False`` is load-bearing: ``RichLog`` defaults to
    ``can_focus = True`` so users can click-and-scroll with the
    keyboard. In the Urika TUI this is the wrong behavior — the
    InputBar should have focus permanently. Otherwise clicking on
    the OutputPanel (which users naturally try to do when they want
    to copy text from it) steals focus away from the InputBar. The
    user then keeps typing, but only some keys land in the input:
    characters that have Input-specific handling (printable chars)
    still appear to work **sometimes** depending on where focus
    happens to be, but keys like space — which are printable but
    have no special handling on the focused RichLog — vanish.
    This produced the "helloworld" effect where spaces were
    silently eaten from typed input.
    """

    can_focus = False
    wrap = True

    # No DEFAULT_CSS border — it was ``border-bottom: solid $accent``
    # which paints a tan/gold line between the panel and the input
    # bar (Textual's ``$accent`` is a warm brown in the default dark
    # theme). The InputBar's own blue border is sufficient visual
    # separation; a second colored line above it is noise. If a
    # border is needed in the future, put it in urika.tcss with an
    # explicit hex so it doesn't pick up the theme color.

    def write_line(self, content: str | Text) -> None:
        """Write a line to the output panel with word-wrapping."""
        self.write(content, expand=True)
