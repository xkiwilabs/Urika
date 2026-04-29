"""Tests for the API-key compliance safety net.

See :mod:`urika.core.compliance` for the rationale: Anthropic's Consumer
Terms §3.7 and the April 2026 Agent SDK clarification prohibit using a
Pro/Max subscription to authenticate the Claude Agent SDK.
"""

from __future__ import annotations

import pytest


class TestHasAPIKey:
    def test_true_when_set_in_agent_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from urika.core.compliance import has_api_key

        assert has_api_key({"ANTHROPIC_API_KEY": "sk-ant-x"}) is True

    def test_true_when_set_in_process_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        from urika.core.compliance import has_api_key

        assert has_api_key(None) is True

    def test_false_when_unset_everywhere(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from urika.core.compliance import has_api_key

        assert has_api_key(None) is False
        assert has_api_key({}) is False
        assert has_api_key({"OTHER": "x"}) is False


class TestIsAnthropicCloudCall:
    def test_true_for_claude_model_with_no_base_url(self):
        from urika.core.compliance import is_anthropic_cloud_call

        assert is_anthropic_cloud_call("claude-haiku-4-5", None) is True
        assert is_anthropic_cloud_call("claude-sonnet-4-5", {}) is True

    def test_false_when_base_url_set(self):
        from urika.core.compliance import is_anthropic_cloud_call

        assert (
            is_anthropic_cloud_call(
                "claude-haiku-4-5",
                {"ANTHROPIC_BASE_URL": "http://localhost:11434"},
            )
            is False
        )

    def test_false_for_non_claude_model(self):
        from urika.core.compliance import is_anthropic_cloud_call

        assert is_anthropic_cloud_call("gpt-4", None) is False
        assert is_anthropic_cloud_call("gemini-pro", None) is False
        assert is_anthropic_cloud_call("ollama/qwen", None) is False


class TestRequireAPIKey:
    def test_raises_on_cloud_call_without_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from urika.core.compliance import APIKeyRequiredError, require_api_key

        with pytest.raises(APIKeyRequiredError) as exc:
            require_api_key("claude-haiku-4-5", None)
        assert "ANTHROPIC_API_KEY" in str(exc.value)
        assert "Consumer Terms" in str(exc.value)

    def test_silent_on_cloud_call_with_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        from urika.core.compliance import require_api_key

        require_api_key("claude-haiku-4-5", None)  # no raise

    def test_silent_on_private_endpoint(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from urika.core.compliance import require_api_key

        require_api_key(
            "claude-haiku-4-5",
            {"ANTHROPIC_BASE_URL": "http://localhost:11434"},
        )  # no raise

    def test_silent_on_non_claude_model(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from urika.core.compliance import require_api_key

        require_api_key("gpt-4", None)  # no raise


class TestScrubOauthEnv:
    def test_strips_oauth_token_var(self):
        from urika.core.compliance import scrub_oauth_env

        out = scrub_oauth_env(
            {
                "ANTHROPIC_API_KEY": "sk-ant-x",
                "CLAUDE_CODE_OAUTH_TOKEN": "oauth-leaked",
            }
        )
        assert out["ANTHROPIC_API_KEY"] == "sk-ant-x"
        assert out["CLAUDE_CODE_OAUTH_TOKEN"] == ""

    def test_strips_anthropic_auth_token_var(self):
        from urika.core.compliance import scrub_oauth_env

        out = scrub_oauth_env({"ANTHROPIC_AUTH_TOKEN": "oauth-leaked"})
        assert out["ANTHROPIC_AUTH_TOKEN"] == ""

    def test_does_not_mutate_input(self):
        from urika.core.compliance import scrub_oauth_env

        original = {"CLAUDE_CODE_OAUTH_TOKEN": "value"}
        scrub_oauth_env(original)
        assert original == {"CLAUDE_CODE_OAUTH_TOKEN": "value"}

    def test_handles_none_input(self):
        from urika.core.compliance import scrub_oauth_env

        out = scrub_oauth_env(None)
        assert out["CLAUDE_CODE_OAUTH_TOKEN"] == ""
        assert out["ANTHROPIC_AUTH_TOKEN"] == ""
