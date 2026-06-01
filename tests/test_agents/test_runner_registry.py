"""Tests for model-prefix → AgentRunner routing.

The companion module ``urika.agents.runner_registry`` exposes
``runner_for(model)`` which selects the right adapter by inspecting
the model name's prefix. Today only ``claude-*`` is wired (the OpenAI
+ Google adapter modules ship in Phase 2/3 of v0.7.0). When those
adapters land, additional routing tests will live alongside their
implementations.
"""

from __future__ import annotations

import pytest

from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
from urika.agents.runner_registry import UnknownModelError, runner_for


def test_claude_models_route_to_claude_runner():
    assert isinstance(runner_for("claude-opus-4-7"), ClaudeSDKRunner)
    assert isinstance(runner_for("claude-sonnet-4-5"), ClaudeSDKRunner)


def test_gpt_models_route_to_openai_runner():
    """``gpt-*`` and ``o3``/``o4``/``o5`` prefixes route to OpenAI adapter.

    The class lives in ``urika.agents.adapters.openai_agents`` and is
    lazily imported by ``runner_for`` so this test exercises the full
    routing path (prefix-match + lazy import + instantiation).
    """
    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    assert isinstance(runner_for("gpt-5.4"), OpenAIAgentsRunner)
    assert isinstance(runner_for("gpt-5.4-mini"), OpenAIAgentsRunner)
    assert isinstance(runner_for("o3"), OpenAIAgentsRunner)


def test_gemini_models_route_to_google_runner():
    """``gemini-*`` prefixes route to the Google ADK adapter.

    The class lives in ``urika.agents.adapters.google_adk`` and is
    lazily imported by ``runner_for`` so this test exercises the full
    routing path (prefix-match + lazy import + instantiation).
    """
    from urika.agents.adapters.google_adk import GoogleADKRunner

    assert isinstance(runner_for("gemini-3.1-pro-preview"), GoogleADKRunner)
    assert isinstance(runner_for("gemini-3.5-flash"), GoogleADKRunner)


def test_unknown_model_raises():
    with pytest.raises(UnknownModelError) as exc:
        runner_for("totally-made-up-model")
    assert "no adapter for model" in str(exc.value).lower()
