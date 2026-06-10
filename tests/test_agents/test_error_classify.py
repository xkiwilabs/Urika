"""Tests for the shared error classification module (extracted in v0.7.1)."""

from urika.agents.error_classify import classify_error


class TestClassifyError:
    def test_config(self):
        assert classify_error("MissingPrivateEndpointError: not configured") == "config"

    def test_rate_limit(self):
        assert classify_error("HTTP 429 Too Many Requests") == "rate_limit"

    def test_auth(self):
        assert classify_error("401 Unauthorized") == "auth"

    def test_billing(self):
        assert classify_error("billing: quota exceeded") == "billing"

    def test_transient(self):
        assert classify_error("HTTP 503 service_unavailable") == "transient"

    def test_unknown_empty(self):
        assert classify_error("") == "unknown"

    def test_max_turns(self):
        # claude-agent-sdk 0.2.91 surfaces max-turns exhaustion as a
        # generic Exception with this message (previously a ProcessError
        # whose str contained "Command failed with exit code").
        assert (
            classify_error(
                "Claude Code returned an error result: "
                "Reached maximum number of turns (20)"
            )
            == "max_turns"
        )

    def test_max_turns_case_insensitive(self):
        assert classify_error("reached MAXIMUM NUMBER OF TURNS (5)") == "max_turns"
