"""Tests for the output panel widget."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestOutputPanel:
    """Test the scrollable output panel.

    Note: RichLog.write() defers rendering until the widget has a known
    size, so we call pilot.pause() to flush one frame before asserting
    on rendered lines. The storage API is `panel.lines` (list[Strip]);
    the older `line_count` attribute was removed in later Textual.
    """

    @pytest.mark.asyncio
    async def test_write_line_appears(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            panel.write_line("Hello from agent")
            await pilot.pause()
            assert len(panel.lines) > 0

    @pytest.mark.asyncio
    async def test_write_rich_text(self) -> None:
        from rich.text import Text

        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            panel.write_line(Text("styled output", style="bold"))
            await pilot.pause()
            assert len(panel.lines) > 0

    @pytest.mark.asyncio
    async def test_panel_cannot_steal_focus(self) -> None:
        """Regression: OutputPanel.can_focus must be False.

        RichLog defaults to can_focus=True so users can click-and-
        keyboard-scroll. In the Urika TUI that's wrong — clicking
        the panel (which users naturally try to do when they want
        to copy text from it) would steal focus from the InputBar.
        Subsequent keys would go to RichLog instead of the input,
        and any key RichLog doesn't have a binding for (notably
        space) would vanish silently, producing the "helloworld"
        space-eating bug reported on the first real-terminal tests.

        Pin the defense: assert can_focus is False AND that
        explicitly calling .focus() on the panel does NOT take
        focus away from InputBar.
        """
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            assert panel.can_focus is False
            assert bar.has_focus is True

            # Even explicit .focus() must not steal focus.
            panel.focus()
            await pilot.pause()
            assert bar.has_focus is True
            assert panel.has_focus is False
