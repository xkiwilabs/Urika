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
            # HACK: `App._exit` is a private Textual attribute. No
            # public equivalent in 8.1.1. Revisit on Textual upgrades;
            # if renamed, wrap self.exit() in our own observable flag.
            assert app._exit is True

    @pytest.mark.asyncio
    async def test_welcome_message_on_mount(self) -> None:
        """The on_mount welcome line was enhanced in Task 10 — see
        test_welcome.py for the full branding/stats/help-hint checks.
        Here we only re-verify that /help is mentioned, because that's
        the dispatch contract these tests care about."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            assert "Urika" in text
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
                # HACK: private Textual attribute — see note on
                # test_quit_command_exits. Asserting False here proves
                # the exception path did NOT exit the app.
                assert app._exit is False
        finally:
            GLOBAL_COMMANDS.pop("boomtest", None)

    @pytest.mark.asyncio
    async def test_slash_command_while_agent_running_shows_busy_hint(self) -> None:
        """Non-escape slash commands submitted while agent_running=True
        must NOT be queued (the queue branch is non-slash only) AND
        must NOT run inline (that would enter self._capture which
        collides with the worker's already-installed OutputCapture).
        They must show a busy hint and fall through cleanly.

        /quit remains a separate escape hatch covered by
        test_quit_command_exits. /stop is an escape hatch covered by
        tests in test_agent_worker.py.
        """
        session = ReplSession()
        session.agent_running = True
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "/help"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            # Busy hint, not /help output.
            assert "busy" in text.lower()
            assert "Commands:" not in text
            # And the slash command was NOT queued.
            assert not session.has_queued_input
            # App still alive — no crash.
            assert app._exit is False

    @pytest.mark.asyncio
    async def test_free_text_with_project_runs_orchestrator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard for the Task 7 review blocker: free text
        with a project loaded must actually run the orchestrator and
        display its response. Previously broken because
        `_handle_free_text` called `asyncio.run(...)` from inside
        Textual's already-running event loop, raising RuntimeError
        that was silently swallowed by the handler's broad except.
        """
        from urika.tui import app as tui_app_module

        calls: list[str] = []

        class StubOrchestrator:
            def __init__(self, project_dir: Path | None = None) -> None:
                self.project_dir = project_dir

            async def chat(self, text: str, **kwargs: object) -> dict:
                calls.append(text)
                return {
                    "response": f"stub reply to: {text}",
                    "success": True,
                    "tokens_in": 5,
                    "tokens_out": 10,
                    "cost_usd": 0.01,
                    "model": "stub-model",
                }

        monkeypatch.setattr(tui_app_module, "OrchestratorChat", StubOrchestrator)

        session = ReplSession()
        session.load_project(path=tmp_path, name="chat-study")

        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "hello agent"
            await pilot.press("enter")

            # Worker coroutine runs on the event loop; multiple pauses
            # give the scheduler a chance to complete it.
            for _ in range(20):
                await pilot.pause()
                if not session.agent_running:
                    break

            text = _panel_text(panel)
            assert calls == ["hello agent"]
            assert "stub reply to: hello agent" in text
            # Session stats were updated from the worker.
            assert session.total_tokens_in >= 5
            assert session.total_tokens_out >= 10
            assert session.model == "stub-model"
            # Worker cleared the running flag on exit.
            assert session.agent_running is False

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
