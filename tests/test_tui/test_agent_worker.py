"""Tests for background agent execution via Textual Workers."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from urika.repl.session import ReplSession
from urika.tui.agent_worker import run_command_in_worker  # noqa: F401
from urika.tui.app import UrikaApp


def _panel_text(panel) -> str:
    """Flatten all rendered Strips in an OutputPanel to plain text."""
    return "\n".join(str(strip) for strip in panel.lines)


class TestAgentWorker:
    """Background worker wiring for blocking slash commands."""

    @pytest.mark.asyncio
    async def test_non_blocking_command(self) -> None:
        """/help is NOT in _BLOCKING_COMMANDS — runs inline, still produces
        output after Task 8's dispatch changes."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            bar = app.query_one("InputBar")
            bar.value = "/help"
            await pilot.press("enter")
            await pilot.pause()
            text = _panel_text(panel)
            # /help emits a "Commands:" header plus its own entry.
            assert "Commands:" in text
            assert "/help" in text

    @pytest.mark.asyncio
    async def test_input_during_agent_run_queues(self) -> None:
        """Non-slash text submitted while agent is running lands in the
        session input queue, not the free-text worker."""
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            bar = app.query_one("InputBar")
            bar.value = "try neural network"
            await pilot.press("enter")
            await pilot.pause()
            assert session.has_queued_input
            assert "neural network" in session.pop_queued_input()

    @pytest.mark.asyncio
    async def test_blocking_command_routes_to_worker(self, tmp_path: Path) -> None:
        """A registered blocking command is dispatched through the
        thread worker: handler runs, output lands in the panel,
        agent_running flips True during execution and False after."""
        from urika.repl.commands import PROJECT_COMMANDS

        started = threading.Event()
        release = threading.Event()
        observed_running: list[bool] = []

        def _fake_run(session, args):
            # Observed from inside the worker thread — proves the
            # lifecycle flag was set before handler invocation.
            observed_running.append(session.agent_running)
            print(f"fake-run handler: {args}")
            started.set()
            # Wait for the test to read agent_running=True.
            release.wait(timeout=2.0)

        # Register our fake as the /run handler (a real blocking command).
        original = PROJECT_COMMANDS.get("run")
        PROJECT_COMMANDS["run"] = {"func": _fake_run, "description": "test"}
        try:
            session = ReplSession()
            # Real Path so StatusBar's load_runtime_config() doesn't
            # choke on a fake filesystem stub.
            session.load_project(path=tmp_path, name="fake")
            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")
                bar.value = "/run baseline"
                await pilot.press("enter")

                # Yield until the worker thread enters the handler.
                for _ in range(50):
                    await pilot.pause()
                    if started.is_set():
                        break
                assert started.is_set(), "worker never entered the handler"

                # While handler blocks, agent_running must be True.
                assert session.agent_running is True

                # Release the handler; wait for completion.
                release.set()
                for _ in range(50):
                    await pilot.pause()
                    if not session.agent_running:
                        break

                # Handler saw agent_running=True at entry.
                assert observed_running == [True]
                # Lifecycle cleared after the worker exits.
                assert session.agent_running is False
                # Handler's print() was captured and routed to the panel.
                text = _panel_text(panel)
                assert "fake-run handler: baseline" in text
        finally:
            if original is not None:
                PROJECT_COMMANDS["run"] = original
            else:
                PROJECT_COMMANDS.pop("run", None)

    @pytest.mark.asyncio
    async def test_blocking_command_rejected_while_agent_running(
        self, tmp_path: Path
    ) -> None:
        """Submitting a blocking slash command while agent_running=True
        must surface a busy hint and NOT invoke the handler. /quit
        remains usable as an escape hatch."""
        from urika.repl.commands import PROJECT_COMMANDS

        calls: list[str] = []

        def _fake_run(session, args):
            calls.append(args)

        original = PROJECT_COMMANDS.get("run")
        PROJECT_COMMANDS["run"] = {"func": _fake_run, "description": "test"}
        try:
            session = ReplSession()
            session.load_project(path=tmp_path, name="fake")
            session.set_agent_running(agent_name="other")

            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")
                bar.value = "/run baseline"
                await pilot.press("enter")
                await pilot.pause()

                text = _panel_text(panel)
                # Busy hint visible.
                assert "busy" in text.lower()
                # Handler was NOT called.
                assert calls == []
                # Agent still marked running (we never cleared it).
                assert session.agent_running is True

                # Escape hatch: /quit still works even while busy.
                bar.value = "/quit"
                await pilot.press("enter")
                await pilot.pause()
                # HACK: private Textual attribute — matches the existing
                # pattern in test_command_dispatch.py::test_quit_command_exits.
                assert app._exit is True
        finally:
            if original is not None:
                PROJECT_COMMANDS["run"] = original
            else:
                PROJECT_COMMANDS.pop("run", None)

    @pytest.mark.asyncio
    async def test_action_cancel_agent_flips_flag(self) -> None:
        """action_cancel_agent clears agent_running and prints a cancel
        notice. Must not crash when called — still a stub, but must
        remain functional after Task 8's changes."""
        session = ReplSession()
        session.set_agent_running(agent_name="task_agent")
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_cancel_agent()
            await pilot.pause()
            assert session.agent_running is False
            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            assert "Agent cancelled" in text
