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
    async def test_input_during_agent_run_queues(self, tmp_path: Path) -> None:
        """Non-slash text submitted while a real worker is running
        lands in the session input queue, not the free-text worker.
        Uses a real gated /run handler (not a synthetic
        agent_running flag) because _on_command self-heals stale
        flags before checking them."""
        from urika.repl.commands import PROJECT_COMMANDS

        started = threading.Event()
        release = threading.Event()

        def _blocking_run(session, args):
            started.set()
            release.wait(timeout=3.0)

        original = PROJECT_COMMANDS.get("run")
        PROJECT_COMMANDS["run"] = {"func": _blocking_run, "description": "test"}
        try:
            session = ReplSession()
            session.load_project(path=tmp_path, name="fake")
            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")

                # Start the real worker via /run.
                bar.value = "/run baseline"
                await pilot.press("enter")
                for _ in range(50):
                    await pilot.pause()
                    if started.is_set():
                        break
                assert started.is_set()

                # Now submit non-slash text — feeds the worker's
                # stdin reader (for interactive prompts) or queues.
                bar.value = "try neural network"
                await pilot.press("enter")
                await pilot.pause()
                text = _panel_text(panel)
                assert "neural network" in text

                release.set()
                for _ in range(50):
                    await pilot.pause()
                    if not session.agent_running:
                        break
        finally:
            if original is not None:
                PROJECT_COMMANDS["run"] = original
            else:
                PROJECT_COMMANDS.pop("run", None)

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
    async def test_blocking_command_rejected_while_real_worker_running(
        self, tmp_path: Path
    ) -> None:
        """Submitting a blocking command while a REAL worker holds an
        OutputCapture must surface a busy hint and NOT invoke the new
        handler. This is the critical regression test for the Task 8
        code-review blocker: merely flipping agent_running isn't
        enough — a real OutputCapture must be active to prove the
        non-reentrant guard isn't crashing the dispatch path.
        """
        from urika.repl.commands import PROJECT_COMMANDS

        started = threading.Event()
        release = threading.Event()
        second_calls: list[str] = []

        def _blocking_run(session, args):
            # Hold the worker open so the second /run is submitted
            # while the first worker's OutputCapture is still live.
            started.set()
            release.wait(timeout=2.0)

        def _second_run(session, args):
            second_calls.append(args)

        original = PROJECT_COMMANDS.get("run")
        PROJECT_COMMANDS["run"] = {"func": _blocking_run, "description": "test"}
        try:
            session = ReplSession()
            session.load_project(path=tmp_path, name="fake")

            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")

                # First dispatch — real worker, holds OutputCapture.
                bar.value = "/run baseline"
                await pilot.press("enter")
                for _ in range(50):
                    await pilot.pause()
                    if started.is_set():
                        break
                assert started.is_set(), "first worker never entered handler"
                assert session.agent_running is True

                # Swap in the SECOND handler and submit another /run.
                PROJECT_COMMANDS["run"] = {
                    "func": _second_run,
                    "description": "test",
                }
                bar.value = "/run secondary"
                await pilot.press("enter")
                await pilot.pause()

                # Second handler must NOT have been called.
                assert second_calls == []
                # Busy hint present in the panel — written through
                # the first worker's _TuiWriter without entering a
                # nested capture.
                text = _panel_text(panel)
                assert "busy" in text.lower()

                # Release first worker and let it drain cleanly.
                release.set()
                for _ in range(50):
                    await pilot.pause()
                    if not session.agent_running:
                        break
                assert session.agent_running is False
        finally:
            if original is not None:
                PROJECT_COMMANDS["run"] = original
            else:
                PROJECT_COMMANDS.pop("run", None)

    @pytest.mark.asyncio
    async def test_non_blocking_command_during_worker_does_not_crash(
        self, tmp_path: Path
    ) -> None:
        """Non-blocking commands (e.g. /help) submitted while a worker
        holds an OutputCapture must not crash the dispatch path. The
        original Task 8 bug: the main-thread ``with self._capture:``
        branch collided with the worker's installed _TuiWriter,
        raising RuntimeError from the non-reentrant guard. Fix
        rerouted non-escape commands to a busy hint (no nested
        capture entry). This test pins that behavior.
        """
        from urika.repl.commands import PROJECT_COMMANDS

        started = threading.Event()
        release = threading.Event()

        def _blocking_run(session, args):
            started.set()
            release.wait(timeout=2.0)

        original = PROJECT_COMMANDS.get("run")
        PROJECT_COMMANDS["run"] = {"func": _blocking_run, "description": "test"}
        try:
            session = ReplSession()
            session.load_project(path=tmp_path, name="fake")

            app = UrikaApp(session=session)
            async with app.run_test() as pilot:
                panel = app.query_one("OutputPanel")
                bar = app.query_one("InputBar")

                bar.value = "/run baseline"
                await pilot.press("enter")
                for _ in range(50):
                    await pilot.pause()
                    if started.is_set():
                        break
                assert started.is_set()
                assert session.agent_running is True

                # Submit /help — non-blocking, non-escape. MUST not
                # crash. The dispatch prints a busy hint directly
                # (not through a new OutputCapture) so the worker's
                # live capture stays intact.
                bar.value = "/help"
                await pilot.press("enter")
                await pilot.pause()

                text = _panel_text(panel)
                assert "busy" in text.lower()
                # And the app is still running — no crash.
                assert app._exit is False

                # Drain worker cleanly.
                release.set()
                for _ in range(50):
                    await pilot.pause()
                    if not session.agent_running:
                        break
                assert session.agent_running is False
        finally:
            if original is not None:
                PROJECT_COMMANDS["run"] = original
            else:
                PROJECT_COMMANDS.pop("run", None)

    @pytest.mark.asyncio
    async def test_action_cancel_agent_writes_flag_and_notifies(
        self, tmp_path: Path
    ) -> None:
        """action_cancel_agent cancels the active worker: writes the
        pause-request flag file, resets agent_running, and prints a
        stop notice."""
        session = ReplSession()
        session.load_project(path=tmp_path, name="fake")
        session.set_agent_running(agent_name="task_agent")

        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_cancel_agent()
            await pilot.pause()

            # Flag file written at the canonical path /stop uses.
            flag_file = tmp_path / ".urika" / "pause_requested"
            assert flag_file.exists()
            assert flag_file.read_text(encoding="utf-8") == "stop"

            # agent_running IS cleared — immediate cancel.
            assert session.agent_running is False

            panel = app.query_one("OutputPanel")
            text = _panel_text(panel)
            assert "Stopped" in text

    @pytest.mark.asyncio
    async def test_action_cancel_agent_quits_when_idle(self) -> None:
        """When no agent is running, Ctrl+C should fall through to
        quit_app — otherwise Ctrl+C is a silent no-op and users with
        no visible keybindings have no escape from the TUI. The
        fall-through writes no cancel-flag file and prints no cancel
        notice; it just triggers app.exit()."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("OutputPanel")
            cancel_lines_before = [
                str(s) for s in panel.lines if "Cancel" in str(s)
            ]

            app.action_cancel_agent()
            await pilot.pause()

            # No cancel notice — falls through to quit, not cancel.
            cancel_lines_after = [
                str(s) for s in panel.lines if "Cancel" in str(s)
            ]
            assert cancel_lines_after == cancel_lines_before
            # HACK: private Textual attribute — matches the HACK
            # annotations in test_command_dispatch.py.
            assert app._exit is True
