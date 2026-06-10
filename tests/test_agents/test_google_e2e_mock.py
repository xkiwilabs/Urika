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

    Note the singular ``static_instruction=`` kwarg. The ADK's
    ``instruction=`` field runs template substitution on literal ``{var}``
    patterns; ``static_instruction=`` is the verbatim-passthrough variant
    Urika uses (system prompts routinely contain ``{method}`` etc.).
    """

    def __init__(self, name, static_instruction, model, tools):  # noqa: ANN001 — fake SDK
        self.name = name
        self.static_instruction = static_instruction
        self.model = model
        self.tools = tools


class _FakePart:
    """Stand-in for ``google.genai.types.Part``."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text


class _FakeContent:
    """Stand-in for ``google.genai.types.Content``."""

    def __init__(
        self, role: str = "model", parts: list[_FakePart] | None = None
    ) -> None:
        self.role = role
        self.parts = parts or []


class _FakeUsageMetadata:
    """Stand-in for ``GenerateContentResponseUsageMetadata``."""

    def __init__(
        self, prompt_token_count: int = 0, candidates_token_count: int = 0
    ) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class _FakeAdkEvent:
    """Stand-in for an ADK ``Event`` — real shape.

    Text rides on ``content.parts[].text`` and tokens ride on
    ``usage_metadata.{prompt,candidates}_token_count``. Same
    contract as the fakes in :file:`test_google_adk.py` — keep them
    aligned with the real ADK API or the structural test in
    :file:`test_google_adk_real_imports.py` flags the drift.
    """

    def __init__(
        self,
        text: str | None = None,
        prompt_token_count: int = 0,
        candidates_token_count: int = 0,
    ) -> None:
        if text is not None:
            self.content = _FakeContent(role="model", parts=[_FakePart(text=text)])
        else:
            self.content = None
        if prompt_token_count or candidates_token_count:
            self.usage_metadata = _FakeUsageMetadata(
                prompt_token_count=prompt_token_count,
                candidates_token_count=candidates_token_count,
            )
        else:
            self.usage_metadata = None


class _FakeAdkRunner:
    """Stand-in for ``google.adk.runners.Runner`` — keyword-only API.

    Mirrors the real ADK ``Runner(*, app_name=, agent=,
    session_service=, auto_create_session=, ...)`` shape so a
    positional-args adapter regression (the v0.7.0 release-blocker
    class) TypeErrors here too.
    """

    def __init__(
        self,
        *,
        app_name: str | None = None,
        agent=None,  # noqa: ANN001 — fake SDK
        session_service=None,  # noqa: ANN001 — fake SDK
        auto_create_session: bool = False,
        **_extra,
    ) -> None:
        assert session_service is not None, "Runner requires session_service"
        self.app_name = app_name
        self.agent = agent
        self.session_service = session_service
        self.auto_create_session = auto_create_session

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message=None,  # noqa: ANN001 — fake SDK (types.Content)
        **_extra,
    ):
        assert new_message is not None, "new_message is required"
        assert hasattr(new_message, "parts"), "new_message must be a Content"
        assert user_id
        assert session_id
        yield _FakeAdkEvent(text="hel")
        yield _FakeAdkEvent(text="lo")
        yield _FakeAdkEvent(prompt_token_count=5, candidates_token_count=2)


class _FakeSessionService:
    """Stand-in for ``InMemorySessionService`` — bare type suffices."""


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
    sessions_mod = type(sys)("google.adk.sessions")
    sessions_mod.InMemorySessionService = _FakeSessionService
    types_mod = type(sys)("google.genai.types")
    types_mod.Content = _FakeContent
    types_mod.Part = _FakePart
    genai_mod = type(sys)("google.genai")
    genai_mod.types = types_mod
    monkeypatch.setitem(sys.modules, "google.adk.agents", agents_mod)
    monkeypatch.setitem(sys.modules, "google.adk.runners", runners_mod)
    monkeypatch.setitem(sys.modules, "google.adk.sessions", sessions_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)

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
