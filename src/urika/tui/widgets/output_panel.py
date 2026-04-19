"""Scrollable output panel for agent output."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import RichLog


class OutputPanel(RichLog):
    """Scrollable panel that displays all agent output.

    ``can_focus = False`` prevents the panel from stealing focus when
    the user clicks on it (which silently ate space keystrokes — see
    the extended comment history in git for the full story).

    ``wrap=True`` is passed through ``__init__`` because RichLog's
    ``__init__`` does ``self.wrap = wrap`` with ``wrap=False`` as the
    default, overriding any class-level ``wrap = True`` we set. The
    only way to actually enable wrapping is to pass it as a
    constructor argument.
    """

    can_focus = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("wrap", True)
        super().__init__(*args, **kwargs)

    def write_line(self, content: str | Text) -> None:
        """Write a line to the output panel with word-wrapping."""
        self.write(content, expand=True)
