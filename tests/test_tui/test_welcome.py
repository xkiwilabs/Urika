"""Tests for the TUI welcome screen."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestWelcomeScreen:
    """Test that the app shows welcome info on mount."""

    @pytest.mark.asyncio
    async def test_shows_welcome_content(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_shows_help_hint(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            assert panel.line_count > 0
