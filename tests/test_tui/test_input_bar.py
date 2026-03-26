"""Tests for the input bar widget."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestInputBar:
    """Test the command input bar."""

    @pytest.mark.asyncio
    async def test_input_bar_exists(self) -> None:
        app = UrikaApp()
        async with app.run_test() as _pilot:
            bar = app.query_one("InputBar")
            assert bar is not None

    @pytest.mark.asyncio
    async def test_input_bar_has_focus(self) -> None:
        app = UrikaApp()
        async with app.run_test() as _pilot:
            bar = app.query_one("InputBar")
            assert bar.has_focus
