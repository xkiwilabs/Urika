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
