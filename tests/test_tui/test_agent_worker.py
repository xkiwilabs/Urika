"""Tests for background agent execution."""

from __future__ import annotations

import pytest

from urika.tui.app import UrikaApp


class TestAgentWorker:
    """Test that agent commands run in background workers."""

    @pytest.mark.asyncio
    async def test_non_blocking_command_via_dispatch(self) -> None:
        """Non-agent commands should work via normal dispatch."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            panel = app.query_one("OutputPanel")
            input_bar = app.query_one("InputBar")
            input_bar.value = "/help"
            await input_bar.action_submit()
            await pilot.pause()
            assert panel.line_count > 0

    @pytest.mark.asyncio
    async def test_input_during_agent_run_queues(self) -> None:
        """User input during agent run should be queued."""
        app = UrikaApp()
        async with app.run_test() as pilot:
            app.session.set_agent_running(agent_name="task_agent")
            input_bar = app.query_one("InputBar")
            input_bar.value = "try neural network"
            await input_bar.action_submit()
            await pilot.pause()
            assert app.session.has_queued_input
            assert "neural network" in app.session.pop_queued_input()
