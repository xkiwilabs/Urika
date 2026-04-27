"""Per-channel health_check() tests.

Covers the non-listening sanity probe each channel exposes for the bus to
filter out misconfigured channels at startup and surface auth errors via the
test-send dashboard endpoint.
"""

from unittest.mock import MagicMock

import pytest


class TestSlackHealthCheck:
    def test_returns_true_on_successful_auth_test(self):
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel({"channel": "#test", "bot_token_env": ""})
        ch._client.auth_test = MagicMock(return_value={"ok": True})
        ok, msg = ch.health_check()
        assert ok is True
        assert msg == ""

    def test_returns_false_on_invalid_auth_with_slack_error_text(self):
        from urika.notifications.slack_channel import SlackChannel

        try:
            from slack_sdk.errors import SlackApiError
        except ImportError:
            pytest.skip("slack-sdk not installed")
        ch = SlackChannel({"channel": "#test", "bot_token_env": ""})

        # Build a SlackApiError with an "error": "invalid_auth" payload.
        fake_response = MagicMock()
        fake_response.get = lambda k, default=None: (
            "invalid_auth" if k == "error" else default
        )
        err = SlackApiError(message="The request failed", response=fake_response)
        ch._client.auth_test = MagicMock(side_effect=err)

        ok, msg = ch.health_check()
        assert ok is False
        assert "invalid_auth" in msg

    def test_returns_false_with_str_exc_on_unexpected_error(self):
        from urika.notifications.slack_channel import SlackChannel

        ch = SlackChannel({"channel": "#test", "bot_token_env": ""})
        ch._client.auth_test = MagicMock(side_effect=RuntimeError("network down"))
        ok, msg = ch.health_check()
        assert ok is False
        assert "network down" in msg


class TestTelegramHealthCheck:
    def test_returns_false_when_no_token(self):
        try:
            from urika.notifications.telegram_channel import TelegramChannel
        except ImportError:
            pytest.skip("python-telegram-bot not installed")
        try:
            ch = TelegramChannel({"chat_id": "123", "bot_token_env": ""})
        except ImportError:
            pytest.skip("python-telegram-bot not installed")
        ok, msg = ch.health_check()
        assert ok is False
        assert "no bot token" in msg.lower()

    # Skip the "valid token" test — it would require network access.


class TestEmailHealthCheck:
    def test_returns_false_when_missing_required_config(self):
        from urika.notifications.email_channel import EmailChannel

        ch = EmailChannel({"from_addr": "x@x.com"})  # no to, no smtp_server
        ok, msg = ch.health_check()
        assert ok is False
        assert (
            "missing" in msg.lower() or "to" in msg.lower() or "smtp" in msg.lower()
        )

    def test_returns_false_when_smtp_server_missing(self):
        """Even with `to`, missing smtp_server should fail closed."""
        from urika.notifications.email_channel import EmailChannel

        ch = EmailChannel({"to": ["x@x.com"], "from_addr": "x@x.com", "smtp_server": ""})
        ok, msg = ch.health_check()
        assert ok is False


class TestBaseHealthCheck:
    def test_default_implementation_returns_true(self):
        from urika.notifications.base import NotificationChannel

        class TrivialChannel(NotificationChannel):
            def send(self, event):
                pass

        ch = TrivialChannel()
        assert ch.health_check() == (True, "")
