"""Tests for the Anthropic subscription-auth path (v0.7.0).

Background: Anthropic's May 13 2026 announcement legitimised authenticating
the Agent SDK via a Pro/Max subscription on or after June 15 2026. Urika's
compliance layer still defaults to ``api_key`` mode (the only mode legal
before June 15, and the safer default afterward for shared/server use),
but users who opt into subscription mode via
``[anthropic] auth = "subscription"`` in ``~/.urika/settings.toml``
get the relaxed pre-spawn check + OAuth-token preservation.

The preference is read via ``compliance._get_anthropic_auth_preference``
so tests can monkeypatch the helper directly without touching disk.
"""

from __future__ import annotations

import pytest


class TestRequireAPIKeyHonoursPreference:
    """Layer 2 of the safety net: the pre-spawn refusal now branches on
    ``_get_anthropic_auth_preference``. ``api_key`` (the default) keeps
    the existing raise-when-missing behaviour; ``subscription`` accepts
    the call without a key (the user has run ``claude login`` and the
    bundled CLI will pick up its stored OAuth token).
    """

    def test_api_key_mode_still_requires_key(self, monkeypatch):
        """Default mode (``api_key``) must keep raising — this is the
        pre-v0.7.0 behaviour and the safe default. Any regression here
        re-introduces a §3.7 violation for users who never opted in.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "api_key",
        )
        from urika.core.compliance import APIKeyRequiredError, require_api_key

        with pytest.raises(APIKeyRequiredError):
            require_api_key("claude-opus-4-7", agent_env={})

    def test_subscription_mode_accepts_no_key(self, monkeypatch):
        """Subscription mode short-circuits the missing-key raise."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "subscription",
        )
        from urika.core.compliance import require_api_key

        # Must not raise.
        require_api_key("claude-opus-4-7", agent_env={})

    def test_subscription_mode_still_no_op_for_private_endpoint(self, monkeypatch):
        """Subscription mode is purely additive — private-endpoint and
        non-claude-model exits keep working.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "subscription",
        )
        from urika.core.compliance import require_api_key

        require_api_key(
            "claude-opus-4-7",
            agent_env={"ANTHROPIC_BASE_URL": "http://localhost:11434"},
        )
        require_api_key("gpt-4", agent_env={})


class TestScrubOauthEnvHonoursPreference:
    """Layer 3 of the safety net: the OAuth scrubber zeroes
    ``CLAUDE_CODE_*`` tokens in ``api_key`` mode (default). In
    subscription mode those tokens are the legitimate auth carrier
    and MUST be preserved when the user has them deliberately set.
    """

    def test_api_key_mode_still_blanks_oauth(self, monkeypatch):
        """Default mode: pre-v0.7.0 behaviour is unchanged."""
        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "api_key",
        )
        from urika.core.compliance import scrub_oauth_env

        out = scrub_oauth_env({"CLAUDE_CODE_OAUTH_TOKEN": "leaked"})
        assert out["CLAUDE_CODE_OAUTH_TOKEN"] == ""

    def test_subscription_mode_preserves_oauth_token(self, monkeypatch):
        """Subscription mode: deliberately-set OAuth tokens pass through.

        The bundled ``claude`` CLI needs the token to authenticate the
        Pro/Max subscription; zeroing it here would defeat the new
        path entirely.
        """
        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "subscription",
        )
        from urika.core.compliance import scrub_oauth_env

        out = scrub_oauth_env(
            {
                "CLAUDE_CODE_OAUTH_TOKEN": "fake-oauth-token",
                "PATH": "/usr/bin",
            }
        )
        assert out["CLAUDE_CODE_OAUTH_TOKEN"] == "fake-oauth-token"
        assert out["PATH"] == "/usr/bin"

    def test_subscription_mode_still_blanks_nested_session_markers(self, monkeypatch):
        """Nested-session markers (``CLAUDECODE``, ``CLAUDE_CODE_SSE_PORT``,
        ...) trip the bundled CLI's nested-launch refusal regardless of
        auth mode, so they must still be zeroed in subscription mode.
        Independent concern from OAuth token preservation.
        """
        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "subscription",
        )
        from urika.core.compliance import _NESTED_SESSION_VARS, scrub_oauth_env

        leaky = {var: "set-by-parent" for var in _NESTED_SESSION_VARS}
        out = scrub_oauth_env(leaky)
        for var in _NESTED_SESSION_VARS:
            assert out[var] == "", f"{var} was not blanked in subscription mode"


class TestGetAnthropicAuthPreference:
    """The settings-backed helper reads ``[anthropic].auth`` from
    ``~/.urika/settings.toml`` via ``URIKA_HOME``. Default is ``api_key``.
    """

    def test_default_is_api_key_when_no_settings_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("URIKA_HOME", str(tmp_path))
        from urika.core.compliance import _get_anthropic_auth_preference

        assert _get_anthropic_auth_preference() == "api_key"

    def test_reads_subscription_from_settings(self, tmp_path, monkeypatch):
        monkeypatch.setenv("URIKA_HOME", str(tmp_path))
        from urika.core.settings import save_settings

        save_settings({"anthropic": {"auth": "subscription"}})
        from urika.core.compliance import _get_anthropic_auth_preference

        assert _get_anthropic_auth_preference() == "subscription"

    def test_reads_api_key_from_settings(self, tmp_path, monkeypatch):
        """An explicit ``api_key`` value round-trips identically to the
        default — no surprise behaviour for users who write the value
        explicitly via ``urika config anthropic`` (Task 4.2).
        """
        monkeypatch.setenv("URIKA_HOME", str(tmp_path))
        from urika.core.settings import save_settings

        save_settings({"anthropic": {"auth": "api_key"}})
        from urika.core.compliance import _get_anthropic_auth_preference

        assert _get_anthropic_auth_preference() == "api_key"


class TestClaudeSDKAdapterDropsAPIKeyInSubscriptionMode:
    """The adapter's child-env builder must remove ``ANTHROPIC_API_KEY``
    in subscription mode so the bundled CLI falls back to its stored
    OAuth token from ``claude login``. Leaving the api key in the
    child env would force api-key auth even when the user explicitly
    opted into subscription mode.
    """

    def test_api_key_dropped_from_child_env_in_subscription_mode(
        self, monkeypatch, tmp_path
    ):
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.agents.config import AgentConfig, SecurityPolicy

        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "subscription",
        )
        cfg = AgentConfig(
            name="t",
            system_prompt="x",
            allowed_tools=["Read"],
            disallowed_tools=[],
            security=SecurityPolicy(
                writable_dirs=[],
                readable_dirs=[tmp_path],
                allowed_bash_prefixes=[],
                blocked_bash_patterns=[],
            ),
            max_turns=1,
            cwd=tmp_path,
            env={"ANTHROPIC_API_KEY": "sk-ant-x", "PATH": "/usr/bin"},
        )
        runner = ClaudeSDKRunner()
        options = runner._build_options(cfg)
        # In subscription mode the api key must NOT be propagated to the
        # spawned subprocess — the bundled CLI would otherwise use it
        # in preference to its stored OAuth token.
        assert "ANTHROPIC_API_KEY" not in options.env or not options.env.get(
            "ANTHROPIC_API_KEY"
        )

    def test_api_key_preserved_in_child_env_in_api_key_mode(
        self, monkeypatch, tmp_path
    ):
        """Default mode (``api_key``) is pre-v0.7.0 behaviour: the key
        must reach the child env so the bundled CLI authenticates via
        the api key.
        """
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.agents.config import AgentConfig, SecurityPolicy

        monkeypatch.setattr(
            "urika.core.compliance._get_anthropic_auth_preference",
            lambda: "api_key",
        )
        cfg = AgentConfig(
            name="t",
            system_prompt="x",
            allowed_tools=["Read"],
            disallowed_tools=[],
            security=SecurityPolicy(
                writable_dirs=[],
                readable_dirs=[tmp_path],
                allowed_bash_prefixes=[],
                blocked_bash_patterns=[],
            ),
            max_turns=1,
            cwd=tmp_path,
            env={"ANTHROPIC_API_KEY": "sk-ant-x", "PATH": "/usr/bin"},
        )
        runner = ClaudeSDKRunner()
        options = runner._build_options(cfg)
        assert options.env.get("ANTHROPIC_API_KEY") == "sk-ant-x"
