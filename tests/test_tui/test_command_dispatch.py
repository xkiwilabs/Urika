"""Tests for command dispatch from InputBar to repl_commands."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestCommandDispatch:
    """Test that slash commands are dispatched to handlers."""

    @pytest.mark.asyncio
    async def test_help_command_produces_output(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/help"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_unknown_command_shows_error(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/nonexistent"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_quit_command_exits(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            input_bar = app.query_one("InputBar")
            input_bar.value = "/quit"
            await input_bar.action_submit()
            await pilot.pause()
