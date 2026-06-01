"""Tests for the Google ADK (Agent Development Kit) adapter.

Task 3.1 ships the skeleton: the class exists, declares the
``AgentRunner`` protocol, and surfaces a clear "extra not installed"
error when the ``google.adk`` SDK modules are absent. Task 3.2 fills
in :meth:`_run_with_sdk` — translating an ``AgentConfig`` into a
``google.adk.agents.Agent``, registering the six shared function
tools, driving the ADK's async event stream via
``google.adk.runners.Runner``, and mapping the SDK's
``LlmResponse`` events back to :class:`AgentResult`.

The adapter is reached via :func:`urika.agents.runner_registry.runner_for`
when the model name starts with ``gemini-``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig, SecurityPolicy


def _make_config(tmp_path: Path) -> AgentConfig:
    """Minimal AgentConfig for adapter tests — gemini-3-pro routed to Google."""
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
        model="gemini-3-pro",
        cwd=tmp_path,
    )


def test_google_runner_importable_when_extra_installed() -> None:
    """If google-adk is locally installed, the runner is importable
    and exposes the AgentRunner ``run`` coroutine.

    Uses ``importorskip`` so the test cleanly skips on dev boxes that
    haven't installed the optional extra — this is still meaningful
    because CI matrices that install ``urika[google]`` will exercise
    the import path.
    """
    pytest.importorskip("google.adk.agents")  # the google-adk SDK module
    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    assert hasattr(runner, "run")
    assert callable(runner.run)


def test_google_runner_raises_clear_error_when_extra_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``google.adk.*`` cannot be imported, ``run`` returns an
    AgentResult with ``success=False`` and an actionable error
    message that points at the ``urika[google]`` extra.

    Both ``google.adk.agents`` and ``google.adk.runners`` are pinned
    to ``None`` because the adapter imports both — if either is
    present the ImportError branch wouldn't fire reliably.
    """
    # Simulate ImportError by setting the modules to None — Python's
    # import machinery treats this as "explicitly absent" and raises.
    monkeypatch.setitem(sys.modules, "google.adk.agents", None)
    monkeypatch.setitem(sys.modules, "google.adk.runners", None)

    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "hi"))
    assert result.success is False
    assert "google-adk" in (result.error or "").lower()
