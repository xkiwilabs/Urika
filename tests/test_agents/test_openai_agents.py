"""Tests for the OpenAI Agents SDK adapter skeleton.

Task 2.1 ships only the skeleton: the class exists, declares the
runner protocol, and surfaces a clear "extra not installed" error
when the ``agents`` SDK module is absent. Task 2.2 will fill in
``_run_with_sdk`` with a real (mocked) call path.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig, SecurityPolicy


def _make_config(tmp_path: Path) -> AgentConfig:
    """Minimal AgentConfig for adapter tests — gpt-5.4 routed to OpenAI."""
    return AgentConfig(
        name="test_agent",
        system_prompt="system here",
        allowed_tools=["Read"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        model="gpt-5.4",
        cwd=tmp_path,
    )


def test_openai_runner_importable_when_extra_installed() -> None:
    """If openai-agents is locally installed, the runner is importable
    and exposes the AgentRunner ``run`` coroutine.

    Uses ``importorskip`` so the test cleanly skips on dev boxes that
    haven't installed the optional extra — this is still meaningful
    because CI matrices that install ``urika[openai]`` will exercise
    the import path.
    """
    pytest.importorskip("agents")  # the openai-agents SDK module
    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    assert hasattr(runner, "run")
    assert callable(runner.run)


def test_openai_runner_raises_clear_error_when_extra_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``agents`` cannot be imported, ``run`` returns an
    AgentResult with ``success=False`` and an actionable error
    message that points at the ``urika[openai]`` extra.
    """
    # Simulate ImportError by setting the module to None — Python's
    # import machinery treats this as "explicitly absent" and raises.
    monkeypatch.setitem(sys.modules, "agents", None)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "hi"))
    assert result.success is False
    assert "openai-agents" in (result.error or "").lower()
