"""Integration tests for the Textual TUI app."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.repl_session import ReplSession
from urika.tui.app import UrikaApp


class TestUrikaAppMount:
    """Test that the app mounts without errors."""

    @pytest.mark.asyncio
    async def test_app_mounts(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.title == "Urika"

    @pytest.mark.asyncio
    async def test_three_zones_present(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.query_one("OutputPanel") is not None
            assert app.query_one("InputBar") is not None
            assert app.query_one("StatusBar") is not None


class TestCommandFlow:
    """Test end-to-end command flows."""

    @pytest.mark.asyncio
    async def test_help_flow(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            initial_count = panel.line_count
            input_bar = app.query_one("InputBar")
            input_bar.value = "/help"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > initial_count

    @pytest.mark.asyncio
    async def test_list_flow(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/list"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_project_command_without_project(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            initial_count = panel.line_count
            input_bar = app.query_one("InputBar")
            input_bar.value = "/status"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > initial_count

    @pytest.mark.asyncio
    async def test_queue_input_while_busy(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            app.session.set_agent_running(agent_name="task_agent")
            input_bar = app.query_one("InputBar")
            input_bar.value = "try ridge regression"
            await input_bar.action_submit()
            await pilot.pause()
            assert app.session.has_queued_input
            queued = app.session.pop_queued_input()
            assert "ridge regression" in queued


class TestSessionIntegration:
    """Test that session state flows through the TUI."""

    @pytest.mark.asyncio
    async def test_session_persists(self) -> None:
        session = ReplSession()
        app = UrikaApp(session=session)
        async with app.run_test() as pilot:
            assert app.session is session

    @pytest.mark.asyncio
    async def test_usage_tracked(self) -> None:
        app = UrikaApp()
        async with app.run_test() as pilot:
            assert app.session.elapsed_ms > 0
