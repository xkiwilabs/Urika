"""Tests for the output panel widget."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestOutputPanel:
    """Test the scrollable output panel."""

    @pytest.mark.asyncio
    async def test_write_line_appears(self) -> None:
        app = UrikaApp()
        async with app.run_test() as _pilot:
            panel = app.query_one("OutputPanel")
            panel.write_line("Hello from agent")
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_write_rich_text(self) -> None:
        from rich.text import Text

        app = UrikaApp()
        async with app.run_test() as _pilot:
            panel = app.query_one("OutputPanel")
            panel.write_line(Text("styled output", style="bold"))
            assert panel.line_count > 0
