"""Tests for command dispatch from InputBar to repl.commands."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


def _panel_text(panel) -> str:
    """Flatten all rendered Strips in an OutputPanel to plain text."""
    return "\n".join(str(strip) for strip in panel.lines)


@contextmanager
def _fake_blocking_run_worker():
    """Temporarily register a fake blocking /run handler and return the
    gate events. The caller dispatches ``/run`` in a real worker which
    then blocks on the ``release`` event — keeping the agent_running
    flag backed by a live Textual worker so the dispatch's self-heal
    doesn't clear it.

    Yields ``(started, release)``. Set release to let the worker finish.
    """
    from urika.repl.commands import PROJECT_COMMANDS

    started = threading.Event()
    release = threading.Event()

    def _blocking_run(session, args):
        started.set()
        release.wait(timeout=3.0)

    original = PROJECT_COMMANDS.get("run")
    PROJECT_COMMANDS["run"] = {"func": _blocking_run, "description": "test"}
    try:
        yield started, release
    finally:
        release.set()  # unblock any still-waiting worker
        if original is not None:
            PROJECT_COMMANDS["run"] = original
        else:
            PROJECT_COMMANDS.pop("run", None)


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
    async def test_free_text_while_agent_running_queues(
        self, tmp_path: Path
    ) -> None:
        """While a real worker is running, non-slash text gets queued.
        The worker must be real (not a synthetic agent_running flag)
        because _on_command now self-heals stale flags — a fake flag
        with no live worker would be cleared before dispatch."""
        session = ReplSession()
        session.load_project(path=tmp_path, name="fake")

        with _fake_blocking_run_worker() as (started, release):
            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")

                # Start the real worker via /run baseline.
                bar.value = "/run baseline"
                await pilot.press("enter")
                for _ in range(50):
                    await pilot.pause()
                    if started.is_set():
                        break
                assert started.is_set()
                assert session.agent_running is True

                # Now submit non-slash text — goes to the queue branch.
                bar.value = "an extra note"
                await pilot.press("enter")
                await pilot.pause()
                text = _panel_text(panel)
                assert "queued" in text
                assert "an extra note" in text
                # And the message actually landed in the session queue.
                assert session.has_queued_input

                # Drain the worker.
                release.set()
                for _ in range(50):
                    await pilot.pause()
                    if not session.agent_running:
                        break

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
    async def test_slash_command_while_agent_running_shows_busy_hint(
        self, tmp_path: Path
    ) -> None:
        """Non-escape slash commands submitted while a real worker is
        running must NOT be queued (the queue branch is non-slash only)
        AND must NOT run inline (that would enter self._capture which
        collides with the worker's already-installed OutputCapture).
        They must show a busy hint and fall through cleanly.

        Uses a REAL gated worker (not a synthetic agent_running flag)
        because _on_command self-heals stale flags.

        /quit remains a separate escape hatch covered by
        test_quit_command_exits. /stop is an escape hatch covered by
        tests in test_agent_worker.py.
        """
        session = ReplSession()
        session.load_project(path=tmp_path, name="fake")

        with _fake_blocking_run_worker() as (started, release):
            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")

                # Start the real worker.
                bar.value = "/run baseline"
                await pilot.press("enter")
                for _ in range(50):
                    await pilot.pause()
                    if started.is_set():
                        break
                assert started.is_set()
                assert session.agent_running is True

                # Now submit /help — should get a busy hint, not execute.
                bar.value = "/help"
                await pilot.press("enter")
                await pilot.pause()
                text = _panel_text(panel)
                assert "busy" in text.lower()
                # And the slash command was NOT queued.
                assert not session.has_queued_input
                # App still alive — no crash.
                assert app._exit is False

                release.set()
                for _ in range(50):
                    await pilot.pause()
                    if not session.agent_running:
                        break

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
    async def test_agent_running_cleared_when_orchestrator_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: if the orchestrator raises any exception
        during a free-text turn, ``session.agent_running`` MUST be
        cleared by the finally block. A previous version set the flag
        BEFORE the try, so any early-path raise (e.g. a NoMatches on
        OutputPanel during app teardown, or an error constructing
        OrchestratorChat) left the flag pinned True and trapped all
        subsequent messages in the queue branch forever.
        """
        from urika.tui import app as tui_app_module

        class FailingOrchestrator:
            def __init__(self, project_dir: Path | None = None) -> None:
                self.project_dir = project_dir

            async def chat(self, text: str, **kwargs: object) -> dict:
                raise RuntimeError("simulated orchestrator failure")

        monkeypatch.setattr(tui_app_module, "OrchestratorChat", FailingOrchestrator)

        session = ReplSession()
        session.load_project(path=tmp_path, name="fail-study")

        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            bar.value = "this will fail"
            await pilot.press("enter")

            for _ in range(20):
                await pilot.pause()
                if not session.agent_running:
                    break

            # Critical: agent_running is cleared even though the
            # orchestrator raised. No trapped-queue state.
            assert session.agent_running is False
            # And the error landed in the panel so the user sees it.
            panel = app.query_one("OutputPanel")
            assert "simulated orchestrator failure" in _panel_text(panel)

    @pytest.mark.asyncio
    async def test_prompt_refreshed_after_command(self, tmp_path: Path) -> None:
        """After a command runs, the input bar's placeholder is refreshed
        so it tracks project state changes.

        Minimum-diagnostic build: the suggester rebuild assertion has
        been dropped (the suggester is absent in this build). Will be
        restored when the suggester comes back.
        """
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            bar = app.query_one("InputBar")
            session.load_project(path=tmp_path, name="refresh-study")
            bar.value = "/help"
            await pilot.press("enter")
            await pilot.pause()
            assert "refresh-study" in bar.placeholder
