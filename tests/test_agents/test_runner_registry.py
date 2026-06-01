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


def test_unknown_model_raises():
    with pytest.raises(UnknownModelError) as exc:
        runner_for("totally-made-up-model")
    assert "no adapter for model" in str(exc.value).lower()
