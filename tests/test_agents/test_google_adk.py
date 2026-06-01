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
from urika.agents.pricing import cost_for


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


# ── Task 3.2: mocked-SDK happy-path + error-path tests ──────────────
#
# The ADK exposes an async event-stream model rather than the OpenAI
# Agents SDK's single awaited ``RunResult``: ``Runner.run_async`` is
# an async iterator that yields ``LlmResponse`` / ``ToolCall`` /
# ``ToolResult`` events. The adapter folds the stream into one
# ``AgentResult`` by accumulating ``event.text`` and pulling token
# counts off the trailing usage-bearing event. The fake below pins
# that contract — text-bearing events, then a final usage event.
#
# Adapter quirk worth flagging: the ADK ``Agent`` constructor uses
# ``instruction=`` (singular), not OpenAI's ``instructions=`` — the
# fake mirrors that so a regression on the keyword name is loud.


class _FakeAdkAgent:
    """Stand-in for ``google.adk.agents.Agent`` — stores ctor args."""

    def __init__(self, name, instruction, model, tools):
        self.name = name
        self.instruction = instruction
        self.model = model
        self.tools = tools


class _FakeAdkEvent:
    """Tiny stand-in for an ADK event (``LlmResponse``-ish).

    Real events would carry richer payloads (tool-call args, etc.);
    the adapter only reads ``text`` for accumulation and
    ``input_tokens`` / ``output_tokens`` for the usage roll-up, so
    that's all the fake needs to expose.
    """

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
        yield _FakeAdkEvent(text="hello ")
        yield _FakeAdkEvent(text="world")
        yield _FakeAdkEvent(input_tokens=80, output_tokens=20, is_final=True)


def _install_fake_adk(monkeypatch: pytest.MonkeyPatch, runner_cls: type) -> None:
    """Install fake ``google.adk.agents`` + ``google.adk.runners``."""
    agents_mod = type(sys)("google.adk.agents")
    agents_mod.Agent = _FakeAdkAgent
    runners_mod = type(sys)("google.adk.runners")
    runners_mod.Runner = runner_cls
    monkeypatch.setitem(sys.modules, "google.adk.agents", agents_mod)
    monkeypatch.setitem(sys.modules, "google.adk.runners", runners_mod)


def test_google_run_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End-to-end (mocked) success path through ``_run_with_sdk``.

    Same shape choice as the OpenAI adapter: token + cost data land
    in the existing flat ``tokens_in`` / ``tokens_out`` / ``cost_usd``
    fields rather than a new ``AgentResult.usage`` dict — downstream
    consumers (usage tab, advisor cost printout) stay backend-agnostic.

    Event-stream folding: the adapter must accumulate ``text`` across
    two text-bearing events ("hello " + "world") and pull the token
    counts off the trailing final event. The on_message callback (if
    provided) fires per text-bearing event — the ADK's stream model
    is the natural place to wire it, unlike the OpenAI adapter.
    """
    _install_fake_adk(monkeypatch, _FakeAdkRunner)

    from urika.agents.adapters.google_adk import GoogleADKRunner

    seen_messages: list[str] = []

    def on_msg(msg: str) -> None:
        seen_messages.append(msg)

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    # Use gemini-3-flash to pin the cheaper price-card row — the
    # base ``_make_config`` defaults to gemini-3-pro for the
    # extra-missing test, but gemini-3-flash gives the simplest
    # cost calculation to assert on (0.00009 USD for 80/20 tokens).
    cfg.model = "gemini-3-flash"
    result = asyncio.run(runner.run(cfg, "user prompt", on_message=on_msg))

    assert result.success is True
    assert result.text_output == "hello world"
    assert result.tokens_in == 80
    assert result.tokens_out == 20
    # cost_for("gemini-3-flash", 80, 20) = (80/1M)*0.50 + (20/1M)*2.50
    #                                    = 0.00004 + 0.00005 = 0.00009
    assert result.cost_usd == pytest.approx(cost_for("gemini-3-flash", 80, 20))
    assert result.cost_usd == pytest.approx(0.00009)
    assert result.model == "gemini-3-flash"
    # The ADK stream-folding model means we *can* fire on_message
    # per text-bearing event — exercise it so the wire-up regresses
    # loudly if a future refactor drops the callback.
    assert seen_messages == ["hello ", "world"]


class _ExplodingAdkRunner:
    """Fake Runner whose ``run_async`` raises mid-stream."""

    def __init__(self, agent):  # noqa: ANN001 — fake SDK
        self.agent = agent

    async def run_async(self, prompt):  # noqa: ANN001 — fake SDK
        # Yield one text event so we can also assert partial-text
        # capture before the failure point.
        yield _FakeAdkEvent(text="partial ")
        raise RuntimeError("gemini api down")


def test_google_run_sdk_error_returned_not_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SDK exceptions surface as ``AgentResult(success=False)``.

    The AgentRunner contract forbids propagating exceptions from
    ``run``. An SDK boundary error (rate-limit, transport, network)
    must become a structured failure so the orchestrator's existing
    pause/resume logic can act on it.
    """
    _install_fake_adk(monkeypatch, _ExplodingAdkRunner)

    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "x"))

    assert result.success is False
    assert "gemini api down" in (result.error or "")
