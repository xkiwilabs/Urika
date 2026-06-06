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
    """Minimal AgentConfig for adapter tests — gemini-3.1-pro-preview routed to Google."""
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
        model="gemini-3.1-pro-preview",
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

    All four import targets (``google.adk.agents``, ``google.adk.runners``,
    ``google.adk.sessions``, ``google.genai``) are pinned to ``None`` —
    the adapter imports all of them in the gating ``try`` block, so if
    any one is present we wouldn't reliably hit the ImportError branch.
    """
    # Simulate ImportError by setting the modules to None — Python's
    # import machinery treats this as "explicitly absent" and raises.
    monkeypatch.setitem(sys.modules, "google.adk.agents", None)
    monkeypatch.setitem(sys.modules, "google.adk.runners", None)
    monkeypatch.setitem(sys.modules, "google.adk.sessions", None)
    monkeypatch.setitem(sys.modules, "google.genai", None)

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
# an async iterator that yields ``Event`` objects (subclassing
# ``LlmResponse``). The adapter folds the stream into one
# ``AgentResult`` by walking ``event.content.parts[].text`` and pulling
# token counts off ``event.usage_metadata`` (``prompt_token_count`` /
# ``candidates_token_count``). The fakes below MUST pin the real ADK
# API shape — that's the v0.7.0 release-blocker lesson: a mock that
# diverges from the real SDK passes its unit test and then explodes
# in the first smoke run. The structural assertions in
# ``test_google_adk_real_imports.py`` keep this contract honest by
# checking the live ADK package; the mocks here are what the adapter
# is exercised against on dev boxes without the [google] extra.
#
# Specifically pinned:
#
# * ``Runner.__init__(*, app_name=..., agent=..., session_service=...,
#   auto_create_session=..., ...)`` — all keyword-only, session_service
#   is REQUIRED in real ADK. Adapter passes ``auto_create_session=True``.
# * ``Runner.run_async(*, user_id, session_id, new_message=...)`` —
#   keyword-only, ``new_message`` is a ``types.Content`` (not str).
# * ``Event.content`` is a ``Content`` with ``.parts`` list, each
#   ``Part`` carrying ``.text``.
# * ``Event.usage_metadata`` exposes ``prompt_token_count`` /
#   ``candidates_token_count``.
# * The ``Agent`` constructor uses ``instruction=`` (singular).


class _FakeAdkAgent:
    """Stand-in for ``google.adk.agents.Agent`` — stores ctor args."""

    def __init__(self, name, instruction, model, tools):
        self.name = name
        self.instruction = instruction
        self.model = model
        self.tools = tools


class _FakePart:
    """Stand-in for ``google.genai.types.Part`` — carries ``text``."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text


class _FakeContent:
    """Stand-in for ``google.genai.types.Content`` — list of parts."""

    def __init__(self, role: str = "model", parts: list[_FakePart] | None = None) -> None:
        self.role = role
        self.parts = parts or []


class _FakeUsageMetadata:
    """Stand-in for ``GenerateContentResponseUsageMetadata``.

    Uses Google's standard naming so a future rename in real ADK
    would be loud at test time (paired with
    ``test_google_adk_real_imports.test_usage_metadata_token_field_names``).
    """

    def __init__(self, prompt_token_count: int = 0, candidates_token_count: int = 0) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class _FakeAdkEvent:
    """Stand-in for an ADK ``Event`` (which subclasses ``LlmResponse``).

    Mirrors the real shape: text rides on ``content.parts[].text`` and
    token counts ride on ``usage_metadata.{prompt,candidates}_token_count``.
    The adapter walks both via ``getattr`` so absent fields are fine.
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
    """Stand-in for ``google.adk.runners.Runner`` — yields 3 events.

    Keyword-only ctor and ``run_async`` mirror the real ADK API. If
    the adapter ever regresses to positional args (the v0.7.0
    release-blocker shape), this fake raises TypeError immediately —
    that's the whole point.
    """

    def __init__(
        self,
        *,
        app_name: str | None = None,
        agent=None,  # noqa: ANN001 — fake SDK
        session_service=None,  # noqa: ANN001 — fake SDK
        auto_create_session: bool = False,
        **_extra,  # forward-compat: tolerate unknown kwargs
    ) -> None:
        # session_service is required in real ADK — if our adapter
        # ever stops passing it, this trips loudly.
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
        # ``new_message`` must be a Content-like object with a parts
        # list — assert the shape so a regression to plain-string is
        # loud here, not at the real-API call site.
        assert new_message is not None, "new_message is required"
        assert hasattr(new_message, "parts"), "new_message must be a Content"
        assert user_id, "user_id must be non-empty"
        assert session_id, "session_id must be non-empty"
        yield _FakeAdkEvent(text="hello ")
        yield _FakeAdkEvent(text="world")
        yield _FakeAdkEvent(prompt_token_count=80, candidates_token_count=20)


class _FakeSessionService:
    """Stand-in for ``InMemorySessionService``.

    The adapter never calls into it (``auto_create_session=True`` lets
    the Runner own the lifecycle), so a bare instance suffices. Real
    ``InMemorySessionService`` has more surface than this — we only
    need the *type* to exist for the import to resolve.
    """


def _install_fake_adk(monkeypatch: pytest.MonkeyPatch, runner_cls: type) -> None:
    """Install fake ``google.adk.{agents,runners,sessions}`` + ``google.genai``.

    All four modules are now needed because ``_run_with_sdk`` imports
    from each: ``Agent``, ``Runner``, ``InMemorySessionService``, and
    ``types`` (for ``Content`` / ``Part``).
    """
    agents_mod = type(sys)("google.adk.agents")
    agents_mod.Agent = _FakeAdkAgent

    runners_mod = type(sys)("google.adk.runners")
    runners_mod.Runner = runner_cls

    sessions_mod = type(sys)("google.adk.sessions")
    sessions_mod.InMemorySessionService = _FakeSessionService

    # ``google.genai`` exposes a ``types`` submodule that the adapter
    # uses for ``types.Content`` and ``types.Part``. Wire both so the
    # adapter's ``from google.genai import types`` resolves.
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
    # Use gemini-3.5-flash to pin the cheaper price-card row — the
    # base ``_make_config`` defaults to gemini-3.1-pro-preview for the
    # extra-missing test, but gemini-3.5-flash gives the simplest
    # cost calculation to assert on (0.0003 USD for 80/20 tokens).
    cfg.model = "gemini-3.5-flash"
    result = asyncio.run(runner.run(cfg, "user prompt", on_message=on_msg))

    assert result.success is True
    assert result.text_output == "hello world"
    assert result.tokens_in == 80
    assert result.tokens_out == 20
    # cost_for("gemini-3.5-flash", 80, 20) = (80/1M)*1.50 + (20/1M)*9.0
    #                                      = 0.00012 + 0.00018 = 0.0003
    assert result.cost_usd == pytest.approx(cost_for("gemini-3.5-flash", 80, 20))
    assert result.cost_usd == pytest.approx(0.0003)
    assert result.model == "gemini-3.5-flash"
    # The ADK stream-folding model means we *can* fire on_message
    # per text-bearing event — exercise it so the wire-up regresses
    # loudly if a future refactor drops the callback.
    assert seen_messages == ["hello ", "world"]


class _ExplodingAdkRunner:
    """Fake Runner whose ``run_async`` raises mid-stream.

    Keyword-only ctor + ``run_async`` mirror the real ADK shape, same
    rationale as ``_FakeAdkRunner`` — a positional-args regression in
    the adapter would TypeError here too.
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
        self.app_name = app_name
        self.agent = agent
        self.session_service = session_service
        self.auto_create_session = auto_create_session

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message=None,  # noqa: ANN001 — fake SDK
        **_extra,
    ):
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
