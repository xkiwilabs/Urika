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
        assert options.permission_mode == "bypassPermissions"

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

    def test_no_can_use_tool(self, read_only_config: AgentConfig) -> None:
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.can_use_tool is None


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

    def test_build_options_preserves_base_url(
        self, read_only_config: AgentConfig
    ) -> None:
        """ANTHROPIC_BASE_URL is preserved through scrubbing."""
        read_only_config.env = {"ANTHROPIC_BASE_URL": "http://localhost:11434"}
        runner = ClaudeSDKRunner()
        options = runner._build_options(read_only_config)
        assert options.env.get("ANTHROPIC_BASE_URL") == "http://localhost:11434"
