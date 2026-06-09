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
