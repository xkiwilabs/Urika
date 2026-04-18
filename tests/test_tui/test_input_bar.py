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
    async def test_input_bar_has_no_placeholder(self) -> None:
        """InputBar has no placeholder text — project/urika info is
        shown in the StatusBar below, not duplicated in the input."""
        app = UrikaApp()
        async with app.run_test():
            bar = app.query_one("InputBar")
            assert bar.placeholder == ""

    @pytest.mark.asyncio
    async def test_refresh_prompt_rebuilds_suggester(self, tmp_path) -> None:
        """refresh_prompt rebuilds the suggester so the completion
        pool reflects the current project's command set."""
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            suggester_before = bar.suggester
            session.load_project(path=tmp_path, name="my-study")
            bar.refresh_prompt()
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
    async def test_extended_key_space_workaround(self) -> None:
        """Regression test for the Textual 8.1.1 extended-key parser bug.

        When a modern terminal (GNOME Terminal / kitty / ghostty /
        WezTerm) uses the modifyOtherKeys / CSI-u extended-key
        protocol, printable keys like space arrive at
        ``Input._on_key`` as ``Key(key="space", character=None)``
        — the multi-char escape sequence around the ``32`` ASCII
        code defeats the parser's ``sequence if len(sequence) == 1
        else None`` logic. Input's ``if event.is_printable:`` check
        then drops the event on the floor and the space vanishes.

        InputBar._on_key works around it by synthesizing the
        character from a known-bug map
        (``_MISSING_CHARACTER_BY_KEY``) when ``character is None``
        and ``key`` matches. This test directly injects a Key event
        shaped exactly like the extended-key regression and asserts
        that the space lands in ``value``.
        """
        from textual.events import Key

        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            bar.value = "hello"
            bar.cursor_position = 5
            await pilot.pause()

            # Simulate the buggy event exactly as the parser emits it.
            buggy_event = Key(key="space", character=None)
            await bar._on_key(buggy_event)
            await pilot.pause()

            assert bar.value == "hello ", (
                f"workaround should have inserted a space; got {bar.value!r}"
            )

    @pytest.mark.asyncio
    async def test_select_on_focus_disabled(self) -> None:
        """Regression: ``select_on_focus`` must be False.

        Textual's Input defaults select_on_focus to True. In a real
        terminal, focus events can fire on redraws / window state
        changes / mouse moves. When a selection is active, the next
        keystroke replaces the selection with a single character —
        which the user observed as "space eats the whole word". The
        bug didn't show up in headless pilot tests because pilot
        doesn't generate spurious focus events. Pin the defense.
        """
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            assert bar.select_on_focus is False

            # Also sanity-check the behavior: after focus, typing
            # "hello" then refocusing then typing space must append
            # a space, not replace the value.
            bar.value = "hello"
            # Force a refocus — in a real terminal this can happen
            # spontaneously.
            bar.blur()
            await pilot.pause()
            bar.focus()
            await pilot.pause()
            # Type a space. Without select_on_focus=False, this
            # would replace "hello" with " ". With the fix, it
            # appends.
            bar.cursor_position = len(bar.value)
            await pilot.press("space")
            await pilot.pause()
            assert bar.value == "hello ", (
                f"space after refocus should append, got {bar.value!r}"
            )

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
