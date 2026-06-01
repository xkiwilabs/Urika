"""End-to-end smoke for the registry → OpenAI runner → mock SDK chain.

Task 2.4 (Phase 2 closer) confirms the wire-up across three modules
that ship across Tasks 1.4, 2.1 and 2.2:

* :func:`urika.agents.runner_registry.runner_for` selects the OpenAI
  adapter for a ``gpt-*`` model string,
* :class:`~urika.agents.adapters.openai_agents.OpenAIAgentsRunner.run`
  translates an :class:`AgentConfig` into an SDK call,
* the SDK's ``RunResult.usage`` is flattened into
  :class:`AgentResult` ``tokens_in`` / ``tokens_out`` / ``cost_usd``.

The existing :file:`test_openai_agents.py` covers the second + third
hops with a hand-rolled fake module. This test goes one level higher
— it instantiates the runner via the registry — so a regression in
the prefix-routing table (e.g. a typo in :mod:`runner_registry`) is
caught even though :file:`test_runner_registry.py` already pins the
``isinstance`` shape, because here the runner is exercised against
real ``AgentConfig`` fields.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig, SecurityPolicy
from urika.agents.pricing import cost_for
from urika.agents.runner_registry import runner_for


class _FakeAgent:
    """Stand-in for ``agents.Agent`` — stores constructor args."""

    def __init__(self, name, instructions, model, tools):  # noqa: ANN001 — fake SDK
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResult:
    final_output = "ok"
    usage = _FakeUsage()


class _FakeRunner:
    @staticmethod
    async def run(agent, prompt, max_turns=10):  # noqa: ANN001 — fake SDK
        return _FakeResult()


def _policy(tmp_path: Path) -> SecurityPolicy:
    """Minimal four-field policy — readable scoped to tmp_path."""
    return SecurityPolicy(
        writable_dirs=[],
        readable_dirs=[tmp_path],
        allowed_bash_prefixes=[],
        blocked_bash_patterns=[],
    )


def test_full_chain_for_gpt_5_4(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``runner_for("gpt-5.4")`` returns a runner that reaches the (faked) SDK.

    Pins the contract that downstream consumers rely on after Task 2.2:
    the success path populates ``cost_usd`` from the shared
    :func:`urika.agents.pricing.cost_for` table, so the orchestrator's
    usage accumulator and the dashboard usage tab keep seeing the same
    numeric type regardless of which provider answered.
    """
    fake = type(sys)("agents")
    fake.Agent = _FakeAgent
    fake.Runner = _FakeRunner
    fake.function_tool = lambda f: f  # no-op decorator
    monkeypatch.setitem(sys.modules, "agents", fake)

    runner = runner_for("gpt-5.4")
    cfg = AgentConfig(
        name="planning_agent",
        system_prompt="s",
        allowed_tools=["Read"],
        disallowed_tools=[],
        security=_policy(tmp_path),
        model="gpt-5.4",
        cwd=tmp_path,
    )

    result = asyncio.run(runner.run(cfg, "p"))

    assert result.success is True
    assert result.text_output == "ok"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    # cost_for("gpt-5.4", 10, 5) = (10/1M)*2.5 + (5/1M)*15
    #                            = 0.000025 + 0.000075 = 0.0001 USD
    assert result.cost_usd == pytest.approx(cost_for("gpt-5.4", 10, 5))
    assert result.cost_usd is not None and result.cost_usd > 0
    assert result.model == "gpt-5.4"
