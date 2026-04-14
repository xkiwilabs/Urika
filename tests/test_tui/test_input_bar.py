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
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            assert "urika>" in bar.placeholder
            # refresh_prompt has two halves: update the placeholder AND
            # rebuild the suggester. Assert both — the suggester contract
            # was uncovered when the review ran.
            suggester_before = bar.suggester
            session.load_project(path=tmp_path, name="my-study")
            bar.refresh_prompt()
            assert "my-study" in bar.placeholder
            assert bar.suggester is not None
            assert bar.suggester is not suggester_before

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

    @pytest.mark.asyncio
    async def test_suggester_completes_commands(self) -> None:
        """The contextual suggester returns real commands for a
        leading /<partial>. ``/he`` → ``/help``, ``/pro`` → ``/project``."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")

            assert await bar.suggester.get_suggestion("/he") == "/help"
            assert await bar.suggester.get_suggestion("/pro") == "/project"
            # No leading slash → no suggestion (free text path).
            assert await bar.suggester.get_suggestion("hello") is None

    @pytest.mark.asyncio
    async def test_tab_accepts_command_suggestion(self) -> None:
        """Pressing Tab on a partial slash command must replace the
        value with the completed command and append a space so the
        user can immediately type an argument."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            bar.value = "/he"
            bar.cursor_position = len(bar.value)
            await pilot.pause()
            await pilot.press("tab")
            await pilot.pause()
            # Tab expanded /he → /help and appended a space.
            assert bar.value == "/help "
            assert bar.cursor_position == len("/help ")

    @pytest.mark.asyncio
    async def test_suggester_completes_project_argument(
        self, tmp_path
    ) -> None:
        """After ``/project <space>``, the suggester switches modes
        and returns project names rather than command names.

        Uses monkeypatch on get_project_names so the test doesn't
        depend on whatever projects happen to exist in the user's
        real ~/.urika registry.
        """
        import urika.repl.commands as rcmd

        fake_projects = ["alpha-study", "beta-study", "gamma-study"]
        orig = rcmd.get_project_names
        rcmd.get_project_names = lambda: fake_projects
        try:
            app = UrikaApp()
            async with app.run_test() as pilot:
                await pilot.pause()
                bar = app.query_one("InputBar")

                # Empty argument → first project.
                assert (
                    await bar.suggester.get_suggestion("/project ")
                    == "/project alpha-study"
                )
                # Partial match → first matching project.
                assert (
                    await bar.suggester.get_suggestion("/project be")
                    == "/project beta-study"
                )
                # No match → None.
                assert await bar.suggester.get_suggestion("/project zzz") is None
        finally:
            rcmd.get_project_names = orig
