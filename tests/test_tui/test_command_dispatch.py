"""Tests for command dispatch from InputBar to repl.commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


def _panel_text(panel) -> str:
    """Flatten all rendered Strips in an OutputPanel to plain text."""
    return "\n".join(str(strip) for strip in panel.lines)


class TestCommandDispatch:
    """Test that slash commands are dispatched to handlers."""

    @pytest.mark.asyncio
    async def test_help_command_produces_output(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "/help"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            # /help lists global commands — "Commands:" header and /help
            # entry must both appear.
            assert "Commands:" in text
            assert "/help" in text

    @pytest.mark.asyncio
    async def test_unknown_command_shows_error(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "/nonexistent"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            assert "Unknown command" in text
            assert "/nonexistent" in text

    @pytest.mark.asyncio
    async def test_project_only_command_without_project_errors(self) -> None:
        """Project-only commands without a project loaded should print a
        'Load a project first' hint — not silently no-op or crash."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            # /report is a PROJECT_COMMAND — guaranteed to need a project.
            bar.value = "/report"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            assert "Load a project first" in text

    @pytest.mark.asyncio
    async def test_quit_command_exits(self) -> None:
        """/quit must call session.save_usage and exit the app."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            bar.value = "/quit"
            await pilot.press("enter")
            await pilot.pause()
            # run_test context exits cleanly; app._exit flag flipped.
            # Textual sets App._exit = True on exit(); verify it.
            assert app._exit is True

    @pytest.mark.asyncio
    async def test_welcome_message_on_mount(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            assert "Welcome to Urika" in text
            assert "/help" in text

    @pytest.mark.asyncio
    async def test_free_text_without_project_shows_hint(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "What's the correlation between age and score?"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            assert "Load a project first" in text

    @pytest.mark.asyncio
    async def test_free_text_while_agent_running_queues(self) -> None:
        session = ReplSession()
        session.agent_running = True  # simulate running agent
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "an extra note"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            assert "queued" in text
            assert "an extra note" in text
            # And the message actually landed in the session input queue.
            assert session.has_queued_input

    @pytest.mark.asyncio
    async def test_handler_exception_printed_not_crashed(self) -> None:
        """A handler that raises must not crash the app — the error is
        printed through OutputCapture and dispatch returns cleanly."""
        from urika.repl.commands import GLOBAL_COMMANDS

        def _boom(session, args):
            raise ValueError("intentional boom")

        GLOBAL_COMMANDS["boomtest"] = {"func": _boom, "description": "test"}
        try:
            app = UrikaApp()
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")
                bar.value = "/boomtest"
                await pilot.press("enter")
                await pilot.pause()
                text = _panel_text(panel)
                assert "Error" in text
                assert "intentional boom" in text
                # App still running.
                assert app._exit is False
        finally:
            GLOBAL_COMMANDS.pop("boomtest", None)

    @pytest.mark.asyncio
    async def test_prompt_refreshed_after_command(self, tmp_path: Path) -> None:
        """After a command runs, the input bar's prompt is refreshed so
        placeholder/suggester track project state changes."""
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            suggester_before = bar.suggester
            # Simulate /project loading by mutating session, then firing
            # a trivial known command (/help) — dispatch should still
            # trigger refresh_prompt at the end.
            session.load_project(path=tmp_path, name="refresh-study")
            bar.value = "/help"
            await pilot.press("enter")
            await pilot.pause()
            assert "refresh-study" in bar.placeholder
            assert bar.suggester is not suggester_before
