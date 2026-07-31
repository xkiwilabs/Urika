"""Scrollable output panel for agent output."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.selection import Selection
from textual.strip import Strip
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

    Text selection: RichLog does not implement Textual's selection
    protocol (the base ``Widget.get_selection`` only handles simple
    Text/Content visuals), so click-drag selected nothing and the
    panel's text could not be copied — the terminal's own selection
    doesn't work either because Textual captures the mouse. The three
    overrides below add it: ``get_selection`` extracts the selected
    text, ``selection_updated`` triggers a repaint, and
    ``_render_line`` paints the selection highlight (mirroring the
    built-in ``Log`` widget, which RichLog never got).
    """

    can_focus = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("wrap", True)
        kwargs.setdefault("max_lines", 10_000)
        super().__init__(*args, **kwargs)

    def write_line(self, content: str | Text) -> None:
        """Write a line to the output panel with word-wrapping.

        ``str`` content with ANSI escape codes is converted to Rich Text
        so the per-agent colours from cli_display (e.g. the
        "──── Finalizer ────" headers) render in colour. Plain strings
        without escapes are unaffected — Text.from_ansi handles both.
        """
        if isinstance(content, str) and "\x1b" in content:
            content = Text.from_ansi(content)
        self.write(content, expand=True)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Extract the text under a mouse selection.

        RichLog stores its content as already-wrapped visual lines
        (``self.lines``, one Strip per rendered row), which is exactly
        the coordinate space the Selection uses — so joining their
        plain text with newlines lets ``selection.extract`` map 1:1.
        """
        text = "\n".join(strip.text for strip in self.lines)
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self.refresh()

    def _render_line(self, y: int, scroll_x: int, width: int) -> Strip:
        """Render a line, painting the selection highlight if any.

        The styled strip is built fresh each call and never cached —
        RichLog's ``_line_cache`` (filled by ``super()._render_line``)
        holds only the unstyled strip, so a cleared selection can't
        leave a stale highlight behind.
        """
        strip = super()._render_line(y, scroll_x, width)
        selection = self.text_selection
        if selection is None:
            return strip
        span = selection.get_span(y)
        if span is None:
            return strip
        start, end = span
        if end == -1:
            end = scroll_x + strip.cell_length
        # Span coordinates are in content space; the strip has been
        # cropped to start at scroll_x.
        start = max(0, start - scroll_x)
        end = max(0, min(end - scroll_x, strip.cell_length))
        if end <= start:
            return strip
        selection_style = self.screen.get_component_rich_style("screen--selection")
        before, middle, after = strip.divide([start, end, strip.cell_length])
        return Strip.join([before, middle.apply_style(selection_style), after])
