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
from typing import Any

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
# * The ``Agent`` constructor takes ``static_instruction=`` (we use
#   ``static_instruction`` rather than ``instruction`` so the ADK
#   template engine does not try to substitute literal ``{var}``
#   patterns from our system prompts).


class _FakeAdkAgent:
    """Stand-in for ``google.adk.agents.Agent`` — stores ctor args."""

    def __init__(self, name, static_instruction, model, tools):
        self.name = name
        self.static_instruction = static_instruction
        self.model = model
        self.tools = tools


class _FakePart:
    """Stand-in for ``google.genai.types.Part`` — carries ``text``."""

    def __init__(self, text: str | None = None) -> None:
        self.text = text


class _FakeContent:
    """Stand-in for ``google.genai.types.Content`` — list of parts."""

    def __init__(
        self, role: str = "model", parts: list[_FakePart] | None = None
    ) -> None:
        self.role = role
        self.parts = parts or []


class _FakeUsageMetadata:
    """Stand-in for ``GenerateContentResponseUsageMetadata``.

    Uses Google's standard naming so a future rename in real ADK
    would be loud at test time (paired with
    ``test_google_adk_real_imports.test_usage_metadata_token_field_names``).
    """

    def __init__(
        self, prompt_token_count: int = 0, candidates_token_count: int = 0
    ) -> None:
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


def test_google_agent_uses_static_instruction_kwarg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pins that ``Agent(static_instruction=...)`` is the kwarg.

    The ADK's ``instruction`` field runs ``inject_session_state`` over
    the prompt and treats every literal ``{var}`` pattern as a context
    variable. Urika prompts routinely embed ``{method}`` / ``{result}``
    in code examples; those would raise ``KeyError`` under
    ``instruction=``. ``static_instruction=`` bypasses that substitution.

    A regression on the kwarg name (e.g. someone "fixing" it back to
    ``instruction``) fails here loudly.
    """
    _install_fake_adk(monkeypatch, _FakeAdkRunner)
    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    # Prompt with literal { } patterns the ADK template engine would
    # otherwise treat as substitution targets. ``_FakeAdkAgent.__init__``
    # accepts ``static_instruction=`` (not ``instruction=``) — if the
    # adapter regresses to ``instruction=``, the construction TypeErrors.
    cfg.system_prompt = "Return JSON like {method: ..., result: ...}"
    cfg.model = "gemini-3.5-flash"
    result = asyncio.run(runner.run(cfg, "user prompt"))

    assert result.success is True, result.error
    # The literal {method}/{result} survived intact in the text_output
    # path because the fake Runner echoes them via the Event stream —
    # if any substitution happened, the assertion would not be the
    # exact prompt content (this test only verifies wiring, not echo).


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


# ── RetryInfo-aware 429 retry handling ──────────────────────────────
#
# Free-tier Gemini accounts hit 5 RPM limits; the unmodified adapter
# surfaces 429 as a hard failure after a single turn, pausing the
# experiment. The retry loop wraps ``runner.run_async`` and parses the
# ``retryDelay`` field that Gemini packs into its 429 response body so
# we honor the server's hint rather than guessing. The "no accumulated
# text" guard keeps retry safe — if the 429 fires mid-stream (rare;
# ADK typically pauses streaming on error) we return the partial text
# rather than re-doing work the model already produced.


class _Rate429Runner:
    """Throws RESOURCE_EXHAUSTED on the first attempt, succeeds on retry.

    Mirrors a real Gemini 429 message shape including the inline JSON-y
    ``retryDelay`` field — the adapter regex must parse this to honor
    the server-suggested backoff window. Uses ``retryDelay: '0.01s'``
    so the test stays fast even before we monkeypatch ``asyncio.sleep``.
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
        self.attempts = 0

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message=None,  # noqa: ANN001 — fake SDK
        **_extra,
    ):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError(
                "429 RESOURCE_EXHAUSTED: Quota exceeded. {'retryDelay': '0.01s'}"
            )
        yield _FakeAdkEvent(text="after retry")
        yield _FakeAdkEvent(prompt_token_count=10, candidates_token_count=5)


# Stash the runner instance so the test can introspect attempt count
# without reaching into the adapter — pytest fixtures would be overkill
# for this one assertion.
_LAST_RUNNER_HOLDER: dict[str, Any] = {}


def _holder_runner(cls: type) -> type:
    """Wrap a fake-runner class so each construction stashes the instance.

    The 429 tests need to assert the number of ``run_async`` attempts,
    which lives on the runner instance. The adapter constructs the
    runner internally so we capture it post-hoc via this wrapper.
    """

    class _Holder(cls):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            _LAST_RUNNER_HOLDER["runner"] = self

    _Holder.__name__ = f"_Holder_{cls.__name__}"
    return _Holder


def test_google_run_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First attempt 429s, second attempt succeeds — surface success.

    Confirms the retry loop parses ``retryDelay`` from the exception
    message, honors it via ``asyncio.sleep`` (monkeypatched to no-op
    for test speed), and restarts ``runner.run_async`` from scratch.
    The "no accumulated text yet" precondition is satisfied because
    the fake raises before yielding any events.
    """
    _install_fake_adk(monkeypatch, _holder_runner(_Rate429Runner))
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(
        "asyncio.sleep",
        lambda *a, **kw: _real_sleep(0),
    )

    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    cfg.model = "gemini-3.5-flash"
    result = asyncio.run(runner.run(cfg, "user prompt"))

    assert result.success is True, result.error
    assert result.text_output == "after retry"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    fake = _LAST_RUNNER_HOLDER["runner"]
    assert fake.attempts == 2, "should retry exactly once before succeeding"


class _Always429Runner:
    """Always throws RESOURCE_EXHAUSTED — used to assert the retry cap."""

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
        self.attempts = 0

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message=None,  # noqa: ANN001 — fake SDK
        **_extra,
    ):
        self.attempts += 1
        raise RuntimeError(
            "429 RESOURCE_EXHAUSTED: persistent quota issue. {'retryDelay': '0.01s'}"
        )
        yield  # pragma: no cover — make this a generator


def test_google_run_429_retry_caps_at_max_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When retries are exhausted, surface ``error_category='rate_limit'``.

    Pins the cap (``_MAX_RETRIES``) — without an upper bound a flapping
    server could pin the agent loop indefinitely. The expected attempt
    count is read from the adapter module so test stays in sync if the
    cap is tuned later.
    """
    _install_fake_adk(monkeypatch, _holder_runner(_Always429Runner))
    _real_sleep = asyncio.sleep
    monkeypatch.setattr(
        "asyncio.sleep",
        lambda *a, **kw: _real_sleep(0),
    )

    from urika.agents.adapters import google_adk as adapter_mod
    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    cfg.model = "gemini-3.5-flash"
    result = asyncio.run(runner.run(cfg, "user prompt"))

    assert result.success is False
    assert result.error_category == "rate_limit"
    assert "RESOURCE_EXHAUSTED" in (result.error or "")
    fake = _LAST_RUNNER_HOLDER["runner"]
    assert fake.attempts == adapter_mod._MAX_RETRIES, (
        f"expected exactly {adapter_mod._MAX_RETRIES} attempts, got {fake.attempts}"
    )


class _GenericFailRunner:
    """Throws a non-429 error on every call — used to assert no retry."""

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
        self.attempts = 0

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message=None,  # noqa: ANN001 — fake SDK
        **_extra,
    ):
        self.attempts += 1
        raise RuntimeError("nope")
        yield  # pragma: no cover — generator marker


def test_google_run_non_429_error_not_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Generic exceptions surface on the first attempt — no retry.

    Retry is opt-in by error class. A network/transport bug or a
    framework error from ADK shouldn't burn through three slow waits
    before failing; the orchestrator's pause/resume logic handles
    those without a backoff hint.
    """
    _install_fake_adk(monkeypatch, _holder_runner(_GenericFailRunner))

    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    cfg.model = "gemini-3.5-flash"
    result = asyncio.run(runner.run(cfg, "user prompt"))

    assert result.success is False
    assert "nope" in (result.error or "")
    # error_category should NOT be rate_limit for non-429 failures.
    assert result.error_category != "rate_limit"
    fake = _LAST_RUNNER_HOLDER["runner"]
    assert fake.attempts == 1, "non-429 errors should not be retried"


# ── Failure-path token + cost preservation (v0.7.0 release-blocker) ─
#
# The AgentResult defaults are tokens_in=0 / tokens_out=0 / cost_usd=None.
# If the failure-path return omits these fields while events have
# already accumulated real usage, the session log records 0 cost for
# work that actually consumed tokens. Compare the Claude SDK adapter,
# which threads ``tokens_in=tokens_in, tokens_out=tokens_out`` (and
# friends) into every ``return AgentResult(success=False, ...)`` site.
# The Google adapter must do the same: the exception handler around
# ``runner.run_async`` covers both the non-retryable mid-stream error
# AND the retries-exhausted branch, so a single fix point preserves
# usage in both cases.


class _AccumulateThenFailRunner:
    """Yields two text+usage events, then throws on the third.

    Mirrors the real ADK stream pattern where usage_metadata accumulates
    incrementally across events. The exception fires AFTER the adapter
    has already updated ``in_tok``/``out_tok`` from the trailing usage
    event — those values must be preserved on the failure AgentResult.
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
        yield _FakeAdkEvent(text="partial ")
        yield _FakeAdkEvent(
            text="output",
            prompt_token_count=100,
            candidates_token_count=20,
        )
        raise RuntimeError("transport reset mid-stream")


def test_google_run_failure_preserves_accumulated_tokens_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Failure path must record real tokens/cost accumulated pre-failure.

    Pre-fix the failure-path ``return AgentResult(success=False, ...)``
    omitted ``tokens_in``/``tokens_out``/``cost_usd``, dropping real
    work into 0 in the session log. Both the mid-stream exception path
    AND the retries-exhausted path go through the same return site, so
    this single test pins both.
    """
    _install_fake_adk(monkeypatch, _AccumulateThenFailRunner)

    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    cfg.model = "gemini-3.5-flash"
    result = asyncio.run(runner.run(cfg, "user prompt"))

    assert result.success is False
    assert "transport reset" in (result.error or "")
    # Token + cost data accumulated pre-failure must be preserved.
    assert result.tokens_in == 100, "tokens_in dropped on failure path"
    assert result.tokens_out == 20, "tokens_out dropped on failure path"
    assert result.cost_usd is not None and result.cost_usd > 0, (
        "cost_usd not recomputed on failure path"
    )
    assert result.cost_usd == pytest.approx(cost_for("gemini-3.5-flash", 100, 20))
    # Partial text should also survive (already worked pre-fix; pin it).
    assert result.text_output == "partial output"


# ── Task 2.2: scrub_oauth_env threaded into Google bash wrapper ──────────────
#
# The bash wrapper in ``_run_with_sdk`` must pass a scrub_oauth_env-cleaned
# env to ``bash_tool`` so OAuth tokens from the parent shell do not leak
# into agent subprocesses.  The fake runner stashes the Agent's tool list
# so the test can invoke the bash wrapper directly and inspect ``env``.


_ADK_RUNNER_HOLDER: dict = {}


class _AgentCapturingAdkRunner(_FakeAdkRunner):
    """Fake Runner that stashes the constructed Agent for inspection."""

    def __init__(self, *, agent=None, **kwargs) -> None:
        super().__init__(agent=agent, **kwargs)
        _ADK_RUNNER_HOLDER["agent"] = agent


def test_google_bash_wrapper_uses_scrubbed_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """bash wrapper passes a scrub_oauth_env-cleaned env to bash_tool.

    A CLAUDE_CODE_OAUTH_TOKEN set in the parent shell must arrive at
    bash_tool as an empty string (zeroed by scrub_oauth_env), not the
    leaked value.

    Strategy: install a runner that stashes the Agent's tool list, then
    invoke the bash wrapper directly to capture the kwargs passed to
    bash_tool.
    """
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "leak")
    _install_fake_adk(monkeypatch, _AgentCapturingAdkRunner)

    captured_kwargs: dict = {}

    from urika.agents.tools import ToolResult
    import urika.agents.tools.bash as bash_mod

    def _fake_bash_tool(cmd: str, **kwargs):
        captured_kwargs.update(kwargs)
        return ToolResult(ok=True, output="ok", error=None, exit_code=0)

    monkeypatch.setattr(bash_mod, "bash", _fake_bash_tool)

    from urika.agents.adapters.google_adk import GoogleADKRunner

    runner = GoogleADKRunner()
    cfg = _make_config(tmp_path)
    cfg.model = "gemini-3.5-flash"

    import asyncio

    asyncio.run(runner.run(cfg, "run bash"))

    # The fake runner stashed the Agent; tools is the list of plain Python
    # functions. Locate the bash wrapper by name.
    agent = _ADK_RUNNER_HOLDER.get("agent")
    assert agent is not None, "runner was not called"
    bash_wrapper = next(
        (t for t in agent.tools if getattr(t, "__name__", "") == "bash"), None
    )
    assert bash_wrapper is not None, "bash tool not in agent.tools"

    # Call the wrapper — it should invoke our fake_bash_tool with env=...
    bash_wrapper("echo hi")

    assert "env" in captured_kwargs, "env kwarg not threaded to bash_tool"
    assert captured_kwargs["env"].get("CLAUDE_CODE_OAUTH_TOKEN") == "", (
        "CLAUDE_CODE_OAUTH_TOKEN was not scrubbed from the bash subprocess env"
    )
