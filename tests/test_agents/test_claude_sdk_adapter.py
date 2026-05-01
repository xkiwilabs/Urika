"""Tests for the Claude Agent SDK adapter.

These tests verify the translation logic without requiring a running
Claude Code instance. SDK calls are mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
from urika.agents.config import AgentConfig, SecurityPolicy


@pytest.fixture
def read_only_config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        name="test_agent",
        system_prompt="You are a test agent.",
        allowed_tools=["Read", "Glob"],
        disallowed_tools=["Bash"],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=5,
        cwd=tmp_path,
    )


@pytest.fixture
def writer_config(tmp_path: Path) -> AgentConfig:
    writable = tmp_path / "methods"
    writable.mkdir()
    return AgentConfig(
        name="writer_agent",
        system_prompt="You can write.",
        allowed_tools=["Read", "Write", "Bash"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[writable],
            readable_dirs=[tmp_path],
            allowed_bash_prefixes=["python "],
            blocked_bash_patterns=["rm -rf"],
        ),
        max_turns=10,
        cwd=tmp_path,
    )


class TestClaudeSDKRunnerBuildOptions:
    def test_maps_basic_fields(self, read_only_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.system_prompt == "You are a test agent."
        assert options.allowed_tools == ["Read", "Glob"]
        assert options.disallowed_tools == ["Bash"]
        assert options.max_turns == 5
        # v0.4: SecurityPolicy enforcement runs via the SDK's
        # ``can_use_tool`` callback, which only fires when
        # ``permission_mode`` is "default" or "acceptEdits".
        # ``bypassPermissions`` skipped the callback entirely
        # pre-v0.4 — that's the bug we just closed.
        assert options.permission_mode == "default"
        assert options.can_use_tool is not None

    def test_maps_cwd(self, read_only_config: AgentConfig, tmp_path: Path) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.cwd == str(tmp_path)

    def test_maps_model(self, read_only_config: AgentConfig) -> None:
        read_only_config.model = "sonnet"
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.model == "sonnet"

    def test_none_cwd_when_not_set(self, read_only_config: AgentConfig) -> None:
        read_only_config.cwd = None
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.cwd is None

    def test_can_use_tool_is_set_for_security_enforcement(
        self, read_only_config: AgentConfig
    ) -> None:
        """v0.4: ``can_use_tool`` is always set so SecurityPolicy
        gets enforced. Pre-v0.4 this was None and policy was
        advisory-only; the test was renamed accordingly."""
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.can_use_tool is not None
        assert callable(options.can_use_tool)


class TestComplianceSafetyNet:
    """Layers 2 + 3 of the API-key safety net (see ``urika.core.compliance``)."""

    @pytest.mark.asyncio
    async def test_run_raises_when_no_api_key_for_cloud_call(
        self, read_only_config: AgentConfig, monkeypatch
    ) -> None:
        """Layer 2 — adapter refuses to spawn when no key for cloud call."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from urika.core.compliance import APIKeyRequiredError

        read_only_config.model = "claude-haiku-4-5"
        read_only_config.env = {}
        runner = ClaudeSDKRunner()
        with pytest.raises(APIKeyRequiredError):
            await runner.run(read_only_config, "hello")

    @pytest.mark.asyncio
    async def test_run_does_not_raise_for_private_endpoint(
        self, read_only_config: AgentConfig, monkeypatch
    ) -> None:
        """Layer 2 exemption — ANTHROPIC_BASE_URL set → no key needed.

        We can't actually run a subprocess in unit tests, but we can
        confirm ``require_api_key`` does not raise. Stubbing ``query``
        lets the run path complete without spawning anything.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        read_only_config.model = "claude-haiku-4-5"
        read_only_config.env = {"ANTHROPIC_BASE_URL": "http://localhost:11434"}

        async def _empty_async_gen(*_args, **_kwargs):
            if False:  # pragma: no cover — unreachable, satisfies async-gen typing
                yield None

        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.query", _empty_async_gen
        )
        runner = ClaudeSDKRunner()
        # Should not raise APIKeyRequiredError; the empty generator
        # produces no messages so the result is a benign empty success.
        result = await runner.run(read_only_config, "hello")
        assert result.success is True

    def test_build_options_scrubs_oauth_token_from_subprocess_env(
        self, read_only_config: AgentConfig
    ) -> None:
        """Layer 3 — spawned subprocess never sees CLAUDE_CODE_OAUTH_TOKEN."""
        read_only_config.env = {
            "ANTHROPIC_API_KEY": "sk-ant-x",
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth-leaked",
        }
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        # Empty string overrides any parent-inherited value
        assert options.env.get("CLAUDE_CODE_OAUTH_TOKEN") == ""
        assert options.env.get("ANTHROPIC_AUTH_TOKEN") == ""
        # API key is preserved
        assert options.env.get("ANTHROPIC_API_KEY") == "sk-ant-x"

    def test_build_options_scrubs_oauth_when_env_is_none(
        self, read_only_config: AgentConfig
    ) -> None:
        """Layer 3 — even when config.env is None, OAuth vars are zeroed."""
        read_only_config.env = None
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.env.get("CLAUDE_CODE_OAUTH_TOKEN") == ""
        assert options.env.get("ANTHROPIC_AUTH_TOKEN") == ""

    def test_build_options_preserves_deliberate_anthropic_auth_token(
        self, read_only_config: AgentConfig
    ) -> None:
        """Regression: when ``build_agent_env_for_endpoint`` sets
        ``ANTHROPIC_AUTH_TOKEN`` deliberately for a non-Anthropic
        OpenAI-compatible private endpoint (Bearer auth), the
        compliance scrub MUST preserve the value. Pre-fix it was
        unconditionally blanked, which 401-ed every private-mode
        run against vLLM/LiteLLM/OpenRouter.
        """
        read_only_config.env = {
            "ANTHROPIC_BASE_URL": "http://100.127.175.6:4200",
            "ANTHROPIC_AUTH_TOKEN": "sk-private-bearer-token",
        }
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.env.get("ANTHROPIC_AUTH_TOKEN") == "sk-private-bearer-token"
        assert options.env.get("ANTHROPIC_BASE_URL") == "http://100.127.175.6:4200"

    def test_build_options_preserves_base_url(
        self, read_only_config: AgentConfig
    ) -> None:
        """ANTHROPIC_BASE_URL is preserved through scrubbing."""
        read_only_config.env = {"ANTHROPIC_BASE_URL": "http://localhost:11434"}
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.env.get("ANTHROPIC_BASE_URL") == "http://localhost:11434"


# ── _classify_error coverage ─────────────────────────────────────────


class TestClassifyError:
    """Error classification drives whether the orchestrator loop
    pauses (recoverable) or fails the experiment outright. The set of
    pausable categories was widened in v0.3.2 to include 'transient'
    (5xx / connection / timeout) and 'config' (missing endpoint /
    missing API key) — pre-v0.3.2 a single network blip mid-loop or
    a misconfigured project killed multi-hour autonomous runs.
    """

    def test_rate_limit_429(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("HTTP 429 Too Many Requests") == "rate_limit"

    def test_auth_401(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("401 Unauthorized") == "auth"

    def test_billing_quota_exceeded(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("billing: quota exceeded") == "billing"

    def test_transient_5xx(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("HTTP 503 service_unavailable") == "transient"

    def test_transient_connection_reset(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert (
            _classify_error("connection reset by peer mid-stream")
            == "transient"
        )

    def test_transient_timeout(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("request timed out after 60s") == "transient"

    def test_config_missing_private_endpoint(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert (
            _classify_error("MissingPrivateEndpointError: not configured")
            == "config"
        )

    def test_config_api_key_required(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("APIKeyRequiredError: no key") == "config"

    def test_unknown_falls_through(self) -> None:
        from urika.agents.adapters.claude_sdk import _classify_error

        assert _classify_error("something completely random") == "unknown"

    def test_pausable_set_includes_new_categories(self) -> None:
        """Regression: the pausable set must include transient and
        config, otherwise the new classifier improvements don't
        actually change loop behavior — the result still gets
        rendered as a hard failure.
        """
        from urika.orchestrator.loop_criteria import _PAUSABLE_ERRORS

        assert "rate_limit" in _PAUSABLE_ERRORS
        assert "billing" in _PAUSABLE_ERRORS
        assert "transient" in _PAUSABLE_ERRORS
        assert "config" in _PAUSABLE_ERRORS


# ── Trailing-exit-1 tolerance ─────────────────────────────────────────


class _FakeAssistantMessage:
    """Minimal stand-in for ``claude_agent_sdk.AssistantMessage``."""

    def __init__(self, text: str, model: str = "claude-opus-4-6") -> None:
        # The adapter checks isinstance(block, TextBlock); we patch
        # TextBlock to this class's block type below.
        self.content = [_FakeTextBlock(text)]
        self.model = model


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResultMessage:
    """Minimal stand-in for ``claude_agent_sdk.ResultMessage``."""

    def __init__(
        self,
        *,
        is_error: bool = False,
        num_turns: int = 1,
        duration_ms: int = 100,
        cost_usd: float = 0.0001,
        result: str = "",
    ) -> None:
        self.session_id = "sess-1"
        self.num_turns = num_turns
        self.duration_ms = duration_ms
        self.is_error = is_error
        self.total_cost_usd = cost_usd
        self.result = result
        self.usage = {"input_tokens": 10, "output_tokens": 5}


class TestTrailingExitTolerance:
    """Regression: system claude CLI v2.1.124+ exits 1 in streaming
    mode after a successful run (the bundled v2.1.63 exits 0). The
    SDK surfaces this as ``Exception("Command failed with exit code
    1")`` *after* yielding the final ``ResultMessage``. Pre-fix urika
    treated this as a hard failure even though the agent's actual
    work completed. The adapter now tolerates the trailing error
    when ``num_turns > 0 and not is_error`` and returns ``success=
    True`` with full state.
    """

    @pytest.mark.asyncio
    async def test_trailing_exit_after_success_is_tolerated(
        self, read_only_config: AgentConfig, monkeypatch
    ) -> None:
        read_only_config.model = "claude-haiku-4-5"
        read_only_config.env = {"ANTHROPIC_API_KEY": "sk-ant-x"}

        async def _fake_query(*_args, **_kwargs):
            yield _FakeAssistantMessage("Hello")
            yield _FakeResultMessage(is_error=False, num_turns=2)
            # Trailing exit-1 mimicking the system CLI bug — raised
            # *after* the ResultMessage was yielded.
            raise Exception("Command failed with exit code 1 (exit code: 1)")

        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.query", _fake_query
        )
        # The adapter checks ``isinstance(msg, AssistantMessage)`` /
        # ``isinstance(msg, ResultMessage)`` — patch those names to
        # our fakes so the type checks pass.
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.AssistantMessage",
            _FakeAssistantMessage,
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.ResultMessage",
            _FakeResultMessage,
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.TextBlock", _FakeTextBlock
        )

        runner = ClaudeSDKRunner()
        result = await runner.run(read_only_config, "hello")

        assert result.success is True, (
            "trailing exit-1 after a clean ResultMessage must be tolerated"
        )
        assert result.text_output == "Hello"
        assert result.num_turns == 2
        assert result.error is None

    @pytest.mark.asyncio
    async def test_trailing_exit_before_result_message_after_content(
        self, read_only_config: AgentConfig, monkeypatch
    ) -> None:
        """Regression: the trailing exit-1 can fire AFTER the last
        AssistantMessage but BEFORE the ResultMessage. text_parts
        is populated, num_turns is still 0. This case must also be
        tolerated — observed in the v0.4 E2E open-mode smoke where
        the advisor's full markdown analysis streamed and suggestions
        were saved to disk, but the SDK raised before the
        ResultMessage arrived.
        """
        read_only_config.model = "claude-haiku-4-5"
        read_only_config.env = {"ANTHROPIC_API_KEY": "sk-ant-x"}

        async def _fake_query(*_args, **_kwargs):
            yield _FakeAssistantMessage("full analysis here")
            # No ResultMessage — trailing exit hits between content
            # and result.
            raise Exception("Command failed with exit code 1 (exit code: 1)")

        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.query", _fake_query
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.AssistantMessage",
            _FakeAssistantMessage,
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.ResultMessage",
            _FakeResultMessage,
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.TextBlock", _FakeTextBlock
        )

        runner = ClaudeSDKRunner()
        result = await runner.run(read_only_config, "hello")

        assert result.success is True, (
            "trailing exit-1 between AssistantMessage and ResultMessage "
            "must be tolerated when text content already streamed"
        )
        assert result.text_output == "full analysis here"
        assert result.num_turns == 0  # no ResultMessage was received

    @pytest.mark.asyncio
    async def test_exit_without_result_message_still_fails(
        self, read_only_config: AgentConfig, monkeypatch
    ) -> None:
        """Counter-test: an exit-1 *before* any AssistantMessage is a
        real failure (e.g. credit-low or auth) and must still surface
        as ``success=False`` with the classified category.
        """
        read_only_config.model = "claude-haiku-4-5"
        read_only_config.env = {"ANTHROPIC_API_KEY": "sk-ant-x"}

        async def _fake_query(*_args, **_kwargs):
            if False:  # pragma: no cover — async-gen typing
                yield None
            raise Exception(
                "Your credit balance is too low to access the Anthropic API."
            )

        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.query", _fake_query
        )

        runner = ClaudeSDKRunner()
        result = await runner.run(read_only_config, "hello")

        assert result.success is False
        assert result.error_category == "billing"
        assert "credit balance" in result.error.lower() or "billing" in result.error.lower()

    @pytest.mark.asyncio
    async def test_trailing_exit_after_is_error_max_turns_is_tolerated(
        self, read_only_config: AgentConfig, monkeypatch
    ) -> None:
        """Regression: when the agent hits ``max_turns`` it emits a
        ResultMessage with ``is_error=True`` (the SDK's standard
        signal), and the bundled CLI then exits 1 in streaming mode
        as the same trailing-exit-1 we tolerate elsewhere. The
        agent's tool calls during those turns already wrote real
        files — the trailing exit is still a CLI shutdown bug, not
        the cause of run failure. Marking the result as failure here
        loses the caller's ability to use what the agent produced
        (observed in the v0.4 E2E open-mode finalize step where the
        Finalizer wrote 50+ files then hit max_turns + trailing
        exit-1).

        Genuine errors (auth, billing, rate-limit) raise different
        exception strings and still surface as failures via the
        post-tolerance branch — covered by
        ``test_exit_without_result_message_still_fails``.
        """
        read_only_config.model = "claude-haiku-4-5"
        read_only_config.env = {"ANTHROPIC_API_KEY": "sk-ant-x"}

        async def _fake_query(*_args, **_kwargs):
            yield _FakeAssistantMessage("partial work product")
            yield _FakeResultMessage(
                is_error=True,
                num_turns=15,
                result="max_turns exceeded",
            )
            raise Exception("Command failed with exit code 1 (exit code: 1)")

        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.query", _fake_query
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.AssistantMessage",
            _FakeAssistantMessage,
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.ResultMessage",
            _FakeResultMessage,
        )
        monkeypatch.setattr(
            "urika.agents.adapters.claude_sdk.TextBlock", _FakeTextBlock
        )

        runner = ClaudeSDKRunner()
        result = await runner.run(read_only_config, "hello")

        # Tolerated: the trailing exit-1 supersedes is_error=True.
        # Caller gets the agent's text content and num_turns to work
        # with downstream.
        assert result.success is True
        assert "partial work product" in result.text_output
        assert result.num_turns == 15

    def test_sdk_logger_filter_drops_fatal_message_reader_line(self) -> None:
        """The SDK's own ``logger.error('Fatal error in message reader: ...')``
        call is suppressed by our adapter-installed filter so it
        doesn't pollute agent output and trip automated smoke
        harnesses.
        """
        import logging

        # Importing the adapter installs the filter as a side effect.
        import urika.agents.adapters.claude_sdk  # noqa: F401

        sdk_logger = logging.getLogger("claude_agent_sdk._internal.query")
        record = sdk_logger.makeRecord(
            sdk_logger.name,
            logging.ERROR,
            __file__,
            0,
            "Fatal error in message reader: Command failed with exit code 1",
            (),
            None,
        )
        # Our filter should drop this specific record.
        keep = all(f.filter(record) for f in sdk_logger.filters)
        assert keep is False, (
            "the trailing-exit suppression filter is missing — SDK noise will leak"
        )

        # Unrelated messages on the same logger must still pass through.
        normal_record = sdk_logger.makeRecord(
            sdk_logger.name,
            logging.ERROR,
            __file__,
            0,
            "Some other error worth seeing",
            (),
            None,
        )
        keep_other = all(f.filter(normal_record) for f in sdk_logger.filters)
        assert keep_other is True
