"""Tests for the status bar widget."""

from __future__ import annotations

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


class TestStatusBar:
    """Test the 2-line status bar."""

    @pytest.mark.asyncio
    async def test_shows_urika_label(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("StatusBar")
            text = bar.render_line1()
            assert "urika" in text.lower()

    @pytest.mark.asyncio
    async def test_shows_project_name(self) -> None:
        session = ReplSession()
        session.load_project(path="/tmp/test", name="my-study")
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            bar = app.query_one("StatusBar")
            text = bar.render_line1()
            assert "my-study" in text

    @pytest.mark.asyncio
    async def test_shows_elapsed_time(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("StatusBar")
            text = bar.render_line2()
            # Should show some elapsed time
            assert "s" in text or "ms" in text
