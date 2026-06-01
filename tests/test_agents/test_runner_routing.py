"""Tests for :mod:`urika.agents.runner_routing`.

The shared helper that resolves an AgentRunner from a project's
runtime config — used by every support-agent call site (v0.7.0 Task
1.5 rewire). Covers:

* Empty project model → default ``ClaudeSDKRunner``.
* Claude model strings → :class:`ClaudeSDKRunner`.
* OpenAI model strings → :class:`OpenAIAgentsRunner`.
* Gemini model strings → :class:`GoogleADKRunner`.
* Per-agent override beats project default.
* Per-agent override absent → falls back to project default.
* Unknown model prefix → falls back to default runner (not an error).
* Missing-extra adapter (simulated ``ModuleNotFoundError`` from the
  registry import) → :class:`AdapterNotInstalledError` with a clear
  ``pip install urika[<provider>]`` hint.
* ``project_path=None`` → default runner (bootstrap paths).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
from urika.agents.runner_routing import (
    AdapterNotInstalledError,
    runner_for_agent,
    runner_for_project,
)


def _write_toml(tmp_path: Path, body: str) -> Path:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "urika.toml").write_text(body, encoding="utf-8")
    return project


# ── runner_for_project ───────────────────────────────────────────────


def test_project_no_toml_returns_default(tmp_path):
    """No ``urika.toml`` → legacy ``get_runner()`` default."""
    project = tmp_path / "proj"
    project.mkdir()
    runner = runner_for_project(project)
    assert isinstance(runner, ClaudeSDKRunner)


def test_project_empty_model_returns_default(tmp_path):
    """``[runtime].model = ""`` → legacy default (back-compat)."""
    project = _write_toml(tmp_path, '[runtime]\nmodel = ""\n')
    runner = runner_for_project(project)
    assert isinstance(runner, ClaudeSDKRunner)


def test_project_claude_model_routes_to_claude(tmp_path):
    project = _write_toml(tmp_path, '[runtime]\nmodel = "claude-opus-4-7"\n')
    runner = runner_for_project(project)
    assert isinstance(runner, ClaudeSDKRunner)


def test_project_gpt_model_routes_to_openai(tmp_path):
    """``gpt-*`` routes to :class:`OpenAIAgentsRunner` via lazy import.

    Exercises the full path: TOML load → ``runner_for`` → lazy import
    of the OpenAI adapter module → instantiation.
    """
    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    project = _write_toml(tmp_path, '[runtime]\nmodel = "gpt-5.4"\n')
    runner = runner_for_project(project)
    assert isinstance(runner, OpenAIAgentsRunner)


def test_project_gemini_model_routes_to_google(tmp_path):
    from urika.agents.adapters.google_adk import GoogleADKRunner

    project = _write_toml(tmp_path, '[runtime]\nmodel = "gemini-3.1-pro-preview"\n')
    runner = runner_for_project(project)
    assert isinstance(runner, GoogleADKRunner)


def test_project_unknown_model_falls_back_to_default(tmp_path):
    """Stray model strings don't break existing setups — fall back."""
    project = _write_toml(tmp_path, '[runtime]\nmodel = "totally-made-up"\n')
    runner = runner_for_project(project)
    assert isinstance(runner, ClaudeSDKRunner)


def test_project_path_none_returns_default():
    """Bootstrap paths with no project still get a runner."""
    runner = runner_for_project(None)
    assert isinstance(runner, ClaudeSDKRunner)


# ── runner_for_agent ─────────────────────────────────────────────────


def test_agent_no_override_uses_project_default(tmp_path):
    """Per-agent override absent → falls back to ``[runtime].model``."""
    project = _write_toml(tmp_path, '[runtime]\nmodel = "claude-opus-4-7"\n')
    runner = runner_for_agent("advisor_agent", project)
    assert isinstance(runner, ClaudeSDKRunner)


def test_agent_override_beats_project_default(tmp_path):
    """``[runtime.models.<agent>].model`` wins over ``[runtime].model``.

    Project default is Claude but the advisor override is GPT — the
    advisor must route to OpenAI even though the project default is
    Claude. This is the precise mixed-provider scenario the rewire
    enables (advisor on OpenAI for reasoning, task agent on Claude
    for execution).
    """
    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    project = _write_toml(
        tmp_path,
        '[runtime]\n'
        'model = "claude-opus-4-7"\n'
        '\n'
        '[runtime.models.advisor_agent]\n'
        'model = "gpt-5.4"\n',
    )
    runner = runner_for_agent("advisor_agent", project)
    assert isinstance(runner, OpenAIAgentsRunner)
    # Sibling agent still uses the project default.
    other = runner_for_agent("task_agent", project)
    assert isinstance(other, ClaudeSDKRunner)


def test_agent_no_project_model_no_override_returns_default(tmp_path):
    """No defaults anywhere → legacy ``get_runner()``."""
    project = tmp_path / "proj"
    project.mkdir()
    runner = runner_for_agent("advisor_agent", project)
    assert isinstance(runner, ClaudeSDKRunner)


def test_agent_path_none_returns_default():
    runner = runner_for_agent("advisor_agent", None)
    assert isinstance(runner, ClaudeSDKRunner)


# ── AdapterNotInstalledError ─────────────────────────────────────────


def test_missing_adapter_extra_raises_actionable_error(monkeypatch, tmp_path):
    """A ``ModuleNotFoundError`` from the adapter import → friendly error.

    Simulates the missing-extra case by monkeypatching
    ``runner_registry.runner_for`` to raise ``ModuleNotFoundError``
    (which is what would happen if a future or third-party adapter
    imported a missing optional dep at module level). The helper
    must re-raise as :class:`AdapterNotInstalledError` with the
    ``pip install urika[<provider>]`` hint embedded.
    """
    from urika.agents import runner_routing

    def _boom(model: str):  # noqa: ARG001
        raise ModuleNotFoundError("No module named 'agents'", name="agents")

    monkeypatch.setattr(runner_routing, "runner_for", _boom, raising=False)
    # The above monkeypatch puts a name in the namespace but _resolve
    # imports ``runner_for`` lazily — patch the source too.
    import urika.agents.runner_registry as _reg

    monkeypatch.setattr(_reg, "runner_for", _boom)

    project = _write_toml(tmp_path, '[runtime]\nmodel = "gpt-5.4"\n')
    with pytest.raises(AdapterNotInstalledError) as exc:
        runner_for_project(project)
    msg = str(exc.value)
    assert "gpt-5.4" in msg
    assert "pip install urika[openai]" in msg


def test_claude_routing_honours_get_runner_patch(monkeypatch, tmp_path):
    """``mock.patch("urika.agents.runner.get_runner")`` must still work.

    This is the canonical test idiom that ~20 existing CLI / REPL /
    RPC tests use to inject fake runners. The v0.7.0 routing rewire
    funnels Claude through ``get_runner`` to preserve the patch path
    — without this, every test that injects a fake runner would
    silently fall back to the real ``ClaudeSDKRunner`` and try to
    hit api.anthropic.com.

    Production semantics are unchanged: both code paths return
    ``ClaudeSDKRunner`` for ``claude-*`` models.
    """
    import urika.agents.runner as _runner_mod

    sentinel = object()
    monkeypatch.setattr(_runner_mod, "get_runner", lambda *a, **k: sentinel)

    project = _write_toml(tmp_path, '[runtime]\nmodel = "claude-opus-4-7"\n')
    assert runner_for_project(project) is sentinel
    # And per-agent too, with both override and project-default paths.
    assert runner_for_agent("advisor_agent", project) is sentinel

    project2 = _write_toml(
        tmp_path / "p2-host",
        '[runtime]\n'
        'model = "claude-opus-4-7"\n'
        '\n'
        '[runtime.models.advisor_agent]\n'
        'model = "claude-sonnet-4-5"\n',
    )
    assert runner_for_agent("advisor_agent", project2) is sentinel


def test_missing_gemini_adapter_extra_hint(monkeypatch, tmp_path):
    """Gemini path gets the ``urika[google]`` hint, not ``urika[openai]``."""
    import urika.agents.runner_registry as _reg

    def _boom(model: str):  # noqa: ARG001
        raise ModuleNotFoundError("No module named 'google.adk'", name="google.adk")

    monkeypatch.setattr(_reg, "runner_for", _boom)

    project = _write_toml(tmp_path, '[runtime]\nmodel = "gemini-3.1-pro-preview"\n')
    with pytest.raises(AdapterNotInstalledError) as exc:
        runner_for_project(project)
    assert "pip install urika[google]" in str(exc.value)
