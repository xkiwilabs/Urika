"""Tests for AgentRunner ABC and AgentResult."""

from __future__ import annotations

import pytest

from urika.agents.runner import AgentResult, AgentRunner


class TestAgentResult:
    def test_successful_result(self) -> None:
        result = AgentResult(
            success=True,
            messages=[{"type": "text", "content": "Hello"}],
            text_output="Hello",
            session_id="session-001",
            num_turns=3,
            duration_ms=1500,
        )
        assert result.success is True
        assert result.cost_usd is None
        assert result.error is None

    def test_failed_result(self) -> None:
        result = AgentResult(
            success=False,
            messages=[],
            text_output="",
            session_id="session-002",
            num_turns=0,
            duration_ms=100,
            error="Connection failed",
        )
        assert result.success is False
        assert result.error == "Connection failed"


class TestAgentRunnerABC:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            AgentRunner()  # type: ignore[abstract]
