"""Tests for the OpenAI Agents SDK adapter.

Task 2.1 shipped the skeleton (class + extra-missing failure path).
Task 2.2 fills in ``_run_with_sdk`` so an ``AgentConfig`` translates
to an ``agents.Agent`` + ``Runner.run`` invocation, with the six
shared function tools (bash/read/write/grep/glob/edit) wired in
through ``ToolRegistry.for_role``. The real SDK call is mocked via
``monkeypatch.setitem(sys.modules, "agents", fake_agents)`` so this
file has no network dependency.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig, SecurityPolicy
from urika.agents.pricing import cost_for


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


# ── Task 2.2: mocked-SDK happy-path + error-path tests ──────────────
#
# The real ``agents`` SDK is replaced with a hand-rolled fake module
# so these tests have no external dependency. The fake mimics the
# three names the adapter touches: ``Agent`` (constructor stash),
# ``Runner.run`` (async classmethod returning a result with
# ``final_output`` + ``usage``), and ``function_tool`` (no-op
# decorator). Adjust the fake's ``usage`` attribute names if the
# real SDK ships with different field names — Task 2.2 implementer
# mirrored the Anthropic "input_tokens / output_tokens" naming the
# openai-agents SDK appears to follow, per its public examples.


class _FakeAgent:
    """Stand-in for ``agents.Agent`` — just stores constructor args."""

    def __init__(self, name, instructions, model, tools):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResult:
    def __init__(self) -> None:
        self.final_output = "the answer is 42"
        self.usage = _FakeUsage(120, 30)


class _FakeRunner:
    @staticmethod
    async def run(agent, prompt, max_turns=10):  # noqa: ANN001 — fake SDK
        # The adapter is expected to pass the AgentConfig.system_prompt
        # through as ``instructions`` and the AgentConfig.model as
        # ``model`` — pin both so a regression here is obvious.
        assert agent.model == "gpt-5.4"
        assert "system here" in agent.instructions
        return _FakeResult()


def _install_fake_agents(monkeypatch: pytest.MonkeyPatch, runner_cls) -> None:
    """Install a fake ``agents`` module with the given Runner class."""
    fake_agents = type(sys)("agents")
    fake_agents.Agent = _FakeAgent
    fake_agents.Runner = runner_cls
    fake_agents.function_tool = lambda f: f  # no-op decorator
    monkeypatch.setitem(sys.modules, "agents", fake_agents)


def test_openai_run_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End-to-end (mocked) success path through ``_run_with_sdk``.

    Path (b) was chosen over adding a public ``AgentResult.usage``
    dict — token + cost data lands in the existing
    ``tokens_in`` / ``tokens_out`` / ``cost_usd`` fields, matching
    what ``ClaudeSDKRunner`` already populates. Keeping the result
    shape uniform across adapters means downstream consumers (usage
    accumulation, dashboard, advisor cost printout) don't branch on
    the backend.
    """
    _install_fake_agents(monkeypatch, _FakeRunner)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "user question"))

    assert result.success is True
    assert "42" in result.text_output
    assert result.tokens_in == 120
    assert result.tokens_out == 30
    # cost_for("gpt-5.4", 120, 30) = (120/1M)*2.5 + (30/1M)*15
    #                              = 0.0003 + 0.00045 = 0.00075
    assert result.cost_usd == pytest.approx(cost_for("gpt-5.4", 120, 30))
    assert result.cost_usd is not None and result.cost_usd > 0
    assert result.model == "gpt-5.4"


class _ExplodingRunner:
    @staticmethod
    async def run(agent, prompt, max_turns=10):  # noqa: ANN001 — fake SDK
        raise RuntimeError("openai api down")


def test_openai_run_sdk_error_returned_not_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SDK exceptions surface as ``AgentResult(success=False)``.

    The AgentRunner contract forbids propagating exceptions from
    ``run``. An SDK boundary error (rate-limit, transport, etc.)
    must become a structured failure so the orchestrator's existing
    pause/resume logic can act on it.
    """
    _install_fake_agents(monkeypatch, _ExplodingRunner)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "x"))

    assert result.success is False
    assert "openai api down" in (result.error or "")
    assert result.text_output == ""


# ── Failure-path token + cost preservation (v0.7.0 release-blocker) ─
#
# Unlike the Google ADK adapter (event-stream), the openai-agents SDK
# is an all-or-nothing awaited ``Runner.run`` — usage rides on the
# success ``RunResult.usage``, and when ``Runner.run`` throws there is
# no partial usage to recover from the SDK itself. The fix is therefore
# defensive: every ``return AgentResult(success=False, ...)`` site
# explicitly sets ``tokens_in=0``, ``tokens_out=0``, and
# ``cost_usd=cost_for(...)`` so downstream consumers don't have to
# distinguish "AgentResult default placeholder" from "real measurement
# saying zero" — they get a uniform float on every adapter / outcome.


def test_openai_run_failure_preserves_accumulated_tokens_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Failure path returns explicit zeros + cost (not the None default).

    The openai-agents SDK doesn't expose partial usage when
    ``Runner.run`` throws (all-or-nothing awaitable), so accumulated
    tokens are zero on the failure path. But the AgentResult still
    needs to set the fields explicitly — pre-fix the failure return
    omitted them, leaving ``cost_usd=None`` (the dataclass default)
    while the success path produces a numeric ``cost_usd``. That
    inconsistency tripped up usage-aggregation consumers that assumed
    cost_usd was always a float once the run had executed.
    """
    _install_fake_agents(monkeypatch, _ExplodingRunner)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "x"))

    assert result.success is False
    # Failure path must explicitly set numeric tokens/cost (not leave
    # AgentResult defaults of ``cost_usd=None``).
    assert result.tokens_in == 0, "tokens_in must be explicitly recorded"
    assert result.tokens_out == 0, "tokens_out must be explicitly recorded"
    assert result.cost_usd is not None, (
        "cost_usd left at None default — failure path skipped the cost_for call"
    )
    assert result.cost_usd == pytest.approx(cost_for("gpt-5.4", 0, 0))
    assert result.cost_usd == 0.0  # 0 tokens at any price card = 0.0


# ── Task 3.2: stream timeout + error categorization ─────────────────
#
# ``Runner.run`` is an all-or-nothing awaitable — a hung HTTP stream
# inside the SDK previously hung the whole orchestrator turn forever.
# The adapter now wraps the call in ``asyncio.wait_for`` honoring the
# same ``URIKA_AGENT_STREAM_TIMEOUT`` knob as the Claude adapter, and
# classifies failure errors via the shared ``classify_error``.


class _HangingRunner:
    @staticmethod
    async def run(agent, prompt, max_turns=10):  # noqa: ANN001 — fake SDK
        await asyncio.sleep(10)
        return _FakeResult()


def test_runner_timeout_returns_transient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hung ``Runner.run`` times out and returns a transient failure."""
    monkeypatch.setenv("URIKA_AGENT_STREAM_TIMEOUT", "0.05")
    _install_fake_agents(monkeypatch, _HangingRunner)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "x"))

    assert result.success is False
    assert result.error_category == "transient"
    assert "timed out" in (result.error or "")
    assert result.cost_usd == pytest.approx(cost_for("gpt-5.4", 0, 0))


class _AuthErrorRunner:
    @staticmethod
    async def run(agent, prompt, max_turns=10):  # noqa: ANN001 — fake SDK
        raise Exception("invalid x-api-key")  # noqa: TRY002 — fake SDK boundary


def test_auth_error_categorized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SDK auth-shaped exceptions get error_category='auth'."""
    _install_fake_agents(monkeypatch, _AuthErrorRunner)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    result = asyncio.run(runner.run(cfg, "x"))

    assert result.success is False
    assert result.error_category == "auth"
    assert "invalid x-api-key" in (result.error or "")


# ── Task 2.2: scrub_oauth_env threaded into OpenAI bash wrapper ─────────────
#
# The bash wrapper in ``_run_with_sdk`` must pass a scrub_oauth_env-cleaned
# env to ``bash_tool`` so OAuth tokens from the parent shell do not leak
# into agent subprocesses.  The fake runner stashes the Agent's tool list
# so the test can invoke the bash wrapper directly and inspect ``env``.


class _ToolCapturingRunner:
    """Fake Runner that stashes the constructed tools list for inspection.

    The agent's tools are registered as function-tool wrappers; this runner
    exposes them so tests can call them directly and assert on their kwargs.
    """

    captured_agent = None

    @staticmethod
    async def run(agent, prompt, max_turns=10):  # noqa: ANN001 — fake SDK
        _ToolCapturingRunner.captured_agent = agent
        return _FakeResult()


def test_openai_bash_wrapper_uses_scrubbed_env(
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
    _install_fake_agents(monkeypatch, _ToolCapturingRunner)

    captured_kwargs: dict = {}

    from urika.agents.tools import ToolResult
    import urika.agents.tools.bash as bash_mod

    def _fake_bash_tool(cmd: str, **kwargs):
        captured_kwargs.update(kwargs)
        return ToolResult(ok=True, output="ok", error=None, exit_code=0)

    monkeypatch.setattr(bash_mod, "bash", _fake_bash_tool)

    from urika.agents.adapters.openai_agents import OpenAIAgentsRunner

    runner = OpenAIAgentsRunner()
    cfg = _make_config(tmp_path)
    import asyncio

    asyncio.run(runner.run(cfg, "run bash"))

    # The fake runner stashed the Agent; the tools list is the registered
    # wrappers.  Locate the bash wrapper by name.
    agent = _ToolCapturingRunner.captured_agent
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
