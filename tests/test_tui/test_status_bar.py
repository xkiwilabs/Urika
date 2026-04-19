"""Tests for the status bar widget."""

from __future__ import annotations

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


class TestStatusBar:
    """Test the single-line status bar."""

    @pytest.mark.asyncio
    async def test_shows_urika_label(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("StatusBar")
            text = bar.render()
            assert "urika" in text.plain.lower()

    @pytest.mark.asyncio
    async def test_shows_project_name(self, tmp_path) -> None:
        session = ReplSession()
        session.load_project(path=tmp_path, name="my-study")
        app = UrikaApp(session=session)
        async with app.run_test():
            bar = app.query_one("StatusBar")
            text = bar.render()
            assert "my-study" in text.plain

    @pytest.mark.asyncio
    async def test_shows_processing_time(self) -> None:
        """Processing time is shown last. It starts at 0ms
        and only ticks while agent_running is True — not session
        uptime. At mount time with no agent running, it reads 0ms."""
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("StatusBar")
            text = bar.render()
            # With no agent run yet, processing time is 0ms.
            assert "0ms" in text.plain, (
                f"expected '0ms' in status bar when idle: {text.plain!r}"
            )
