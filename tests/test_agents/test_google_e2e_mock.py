"""End-to-end smoke for the registry → Google ADK runner → mock SDK chain.

Task 3.4 (Phase 3 closer) confirms the wire-up across three modules
that ship across Tasks 1.4, 3.1 and 3.2:

* :func:`urika.agents.runner_registry.runner_for` selects the Google
  adapter for a ``gemini-*`` model string,
* :class:`~urika.agents.adapters.google_adk.GoogleADKRunner.run`
  translates an :class:`AgentConfig` into an ADK call and folds the
  async event stream into one result,
* the trailing event's ``input_tokens`` / ``output_tokens`` flatten
  into :class:`AgentResult` ``tokens_in`` / ``tokens_out`` /
  ``cost_usd``.

The existing :file:`test_google_adk.py` covers the second + third
hops with hand-rolled fake modules. This test goes one level higher
— it instantiates the runner via the registry — so a regression in
the prefix-routing table (e.g. a typo in :mod:`runner_registry`) is
caught even though :file:`test_runner_registry.py` already pins the
``isinstance`` shape, because here the runner is exercised against
real ``AgentConfig`` fields. Mirror of :file:`test_openai_e2e_mock.py`
(Task 2.4) for the other cloud adapter.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig, SecurityPolicy
from urika.agents.pricing import cost_for
from urika.agents.runner_registry import runner_for


class _FakeAdkAgent:
    """Stand-in for ``google.adk.agents.Agent`` — stores ctor args.

    Note the singular ``instruction=`` kwarg — that's the ADK's
    constructor signature (the OpenAI Agents SDK uses ``instructions=``
    plural). A regression on this keyword name is loud here.
    """

    def __init__(self, name, instruction, model, tools):  # noqa: ANN001 — fake SDK
        self.name = name
        self.instruction = instruction
        self.model = model
        self.tools = tools


class _FakeAdkEvent:
    """Stand-in for an ADK event — carries text or usage counts."""

    def __init__(
        self,
        text: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        is_final: bool = False,
    ) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.is_final = is_final


class _FakeAdkRunner:
    """Stand-in for ``google.adk.runners.Runner`` — yields 3 events."""

    def __init__(self, agent):  # noqa: ANN001 — fake SDK
        self.agent = agent

    async def run_async(self, prompt):  # noqa: ANN001 — fake SDK
        yield _FakeAdkEvent(text="hel")
        yield _FakeAdkEvent(text="lo")
        yield _FakeAdkEvent(input_tokens=5, output_tokens=2, is_final=True)


def _policy(tmp_path: Path) -> SecurityPolicy:
    """Minimal four-field policy — readable scoped to tmp_path."""
    return SecurityPolicy(
        writable_dirs=[],
        readable_dirs=[tmp_path],
        allowed_bash_prefixes=[],
        blocked_bash_patterns=[],
    )


def test_full_chain_for_gemini_3_flash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``runner_for("gemini-3.5-flash")`` reaches the (faked) ADK SDK.

    Pins the contract that downstream consumers rely on after Task
    3.2: the success path populates ``cost_usd`` from the shared
    :func:`urika.agents.pricing.cost_for` table, so the orchestrator's
    usage accumulator and the dashboard usage tab keep seeing the
    same numeric type regardless of which provider answered.
    """
    agents_mod = type(sys)("google.adk.agents")
    agents_mod.Agent = _FakeAdkAgent
    runners_mod = type(sys)("google.adk.runners")
    runners_mod.Runner = _FakeAdkRunner
    monkeypatch.setitem(sys.modules, "google.adk.agents", agents_mod)
    monkeypatch.setitem(sys.modules, "google.adk.runners", runners_mod)

    runner = runner_for("gemini-3.5-flash")
    cfg = AgentConfig(
        name="planning_agent",
        system_prompt="s",
        allowed_tools=["Read"],
        disallowed_tools=[],
        security=_policy(tmp_path),
        model="gemini-3.5-flash",
        cwd=tmp_path,
    )

    result = asyncio.run(runner.run(cfg, "p"))

    assert result.success is True
    assert result.text_output == "hello"
    assert result.tokens_in == 5
    assert result.tokens_out == 2
    # cost_for("gemini-3.5-flash", 5, 2) = (5/1M)*1.50 + (2/1M)*9.0
    #                                    = 0.0000075 + 0.000018 = 0.0000255 USD
    assert result.cost_usd == pytest.approx(cost_for("gemini-3.5-flash", 5, 2))
    assert result.cost_usd == pytest.approx(0.0000255)
    assert result.cost_usd is not None and result.cost_usd > 0
    assert result.model == "gemini-3.5-flash"
