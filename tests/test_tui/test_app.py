"""Tests for the Textual TUI app."""

from __future__ import annotations

import pytest


class TestUrikaAppMount:
    """Test that the app mounts without errors."""

    @pytest.mark.asyncio
    async def test_app_mounts(self) -> None:
        from urika.tui.app import UrikaApp

        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.title == "Urika"
