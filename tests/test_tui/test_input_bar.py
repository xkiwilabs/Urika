"""Tests for the input bar widget."""

from __future__ import annotations

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


class TestInputBar:
    """Test the command input bar."""

    @pytest.mark.asyncio
    async def test_input_bar_exists(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("InputBar")
            assert bar is not None

    @pytest.mark.asyncio
    async def test_input_bar_has_focus(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            # on_mount calls self.focus(); pause to let mount events settle.
            await pilot.pause()
            assert bar.has_focus

    @pytest.mark.asyncio
    async def test_prompt_shows_urika(self) -> None:
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("InputBar")
            assert "urika" in bar.placeholder.lower()

    @pytest.mark.asyncio
    async def test_prompt_shows_project_name(self, tmp_path) -> None:
        session = ReplSession()
        session.load_project(path=tmp_path, name="my-study")
        app = UrikaApp(session=session)
        async with app.run_test():
            bar = app.query_one("InputBar")
            assert "my-study" in bar.placeholder

    @pytest.mark.asyncio
    async def test_refresh_prompt_after_project_change(self, tmp_path) -> None:
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test():
            bar = app.query_one("InputBar")
            assert "urika>" in bar.placeholder
            session.load_project(path=tmp_path, name="my-study")
            bar.refresh_prompt()
            assert "my-study" in bar.placeholder

    @pytest.mark.asyncio
    async def test_submit_emits_command_and_clears(self) -> None:
        from urika.tui.widgets.input_bar import InputBar

        received: list[str] = []

        class CapturingApp(UrikaApp):
            def on_input_bar_command_submitted(
                self, message: InputBar.CommandSubmitted
            ) -> None:
                received.append(message.value)

        app = CapturingApp()
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            bar.value = "/help"
            await pilot.press("enter")
            await pilot.pause()
            assert received == ["/help"]
            assert bar.value == ""

    @pytest.mark.asyncio
    async def test_suggester_built_from_commands(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            assert bar.suggester is not None
