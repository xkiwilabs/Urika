"""Tests for the POST /api/settings/notifications/test-send endpoint.

The endpoint sends a synthetic test notification through every channel
that the form configures, building channels from un-saved form data so
users can validate creds before clicking Save.
"""

from __future__ import annotations


def test_test_send_with_no_channels_configured_returns_empty_list(settings_client):
    """No required fields supplied -> no channels constructed -> empty list."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"channels": []}


def test_test_send_with_email_smtp_unreachable_returns_email_result(settings_client):
    """Email creds with an unreachable SMTP server still produce a
    channel result entry. EmailChannel.send swallows SMTP errors and
    logs them, so the status may be reported as 'ok' even though the
    underlying send failed — the test asserts the endpoint runs
    without crashing and the channel appears in the results list."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
            "notifications_email_smtp_host": "127.0.0.1",
            "notifications_email_smtp_port": "1",  # nothing listening
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "channels" in body
    email_results = [c for c in body["channels"] if c["name"] == "EmailChannel"]
    assert len(email_results) == 1
    # EmailChannel.send swallows exceptions internally — report can be
    # either 'ok' or 'error' depending on whether the constructor or
    # send raised. The point is the endpoint ran cleanly.
    assert email_results[0]["status"] in {"ok", "error"}


def test_test_send_skips_email_when_only_from_set(settings_client):
    """Email channel needs both from AND to. Only from -> not built."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_email_from": "bot@example.com",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"channels": []}


def test_test_send_skips_email_when_only_to_set(settings_client):
    """Email channel needs both from AND to. Only to -> not built."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_email_to": "alice@example.com",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"channels": []}


def test_test_send_with_slack_channel_only_attempts_slack(settings_client):
    """Slack just needs a channel set to be attempted. With no real
    token env, the construction may fail (slack-sdk not installed) or
    the send may fail — either way the channel surfaces in the response."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_slack_channel": "#urika-test",
            "notifications_slack_token_env": "NONEXISTENT_SLACK_TOKEN",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "channels" in body
    slack_results = [c for c in body["channels"] if c["name"] == "SlackChannel"]
    # Either constructed and reported (ok/error) or construction failed
    # because slack-sdk is missing — both yield exactly one entry.
    assert len(slack_results) == 1
    assert slack_results[0]["status"] in {"ok", "error"}


def test_test_send_with_telegram_minimum_attempts_telegram(settings_client):
    """Telegram needs both chat_id and bot_token_env. With both set
    the channel is constructed (or its construction error is captured)
    and surfaces in the response."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_telegram_chat_id": "-1001234567890",
            "notifications_telegram_bot_token_env": "NONEXISTENT_TELEGRAM_TOKEN",
        },
    )
    assert r.status_code == 200
    body = r.json()
    tg_results = [c for c in body["channels"] if c["name"] == "TelegramChannel"]
    assert len(tg_results) == 1
    assert tg_results[0]["status"] in {"ok", "error"}


def test_test_send_skips_telegram_when_only_chat_id_set(settings_client):
    """Telegram needs both chat_id AND bot_token_env."""
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_telegram_chat_id": "-1001234567890",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"channels": []}


def test_test_send_does_not_persist_settings(settings_client, tmp_path):
    """Test-send must NEVER write to settings.toml."""
    settings_toml = tmp_path / "home" / "settings.toml"
    pre_existed = settings_toml.exists()
    pre_content = settings_toml.read_text() if pre_existed else None

    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
        },
    )
    assert r.status_code == 200

    if pre_existed:
        assert settings_toml.read_text() == pre_content
    else:
        assert not settings_toml.exists()


def test_test_send_refreshes_secrets_env(settings_client, tmp_path, monkeypatch):
    """Regression: test-send must reload secrets.env so newly-added vars
    are visible to channel constructors. Otherwise the long-lived dashboard
    process can't see credentials added via `urika notifications` in
    another shell since startup."""
    import os

    # Point the secrets file at a temp location and write a fresh secret
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text("FRESH_TOKEN=xoxb-just-added\n")
    monkeypatch.setattr(
        "urika.core.secrets._SECRETS_PATH", secrets_path
    )
    # Ensure the variable is NOT already in os.environ
    monkeypatch.delenv("FRESH_TOKEN", raising=False)
    assert "FRESH_TOKEN" not in os.environ

    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_slack_channel": "#urika",
            "notifications_slack_token_env": "FRESH_TOKEN",
        },
    )
    assert r.status_code == 200
    # The endpoint should have called load_secrets() and the FRESH_TOKEN
    # value is now visible to subsequent channel reads (we don't assert
    # the channel succeeded — just that the var was loaded).
    assert os.environ.get("FRESH_TOKEN") == "xoxb-just-added"


def test_test_send_construction_failure_surfaces_in_response(
    settings_client, monkeypatch
):
    """If a channel constructor raises (e.g. import error for slack_sdk
    or a config-validation error), the failure is captured as an
    'error' entry rather than crashing the request."""

    def boom(_cfg):
        raise RuntimeError("boom: constructor failed")

    monkeypatch.setattr(
        "urika.notifications.email_channel.EmailChannel.__init__",
        boom,
    )
    r = settings_client.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
        },
    )
    assert r.status_code == 200
    body = r.json()
    email_results = [c for c in body["channels"] if c["name"] == "EmailChannel"]
    assert len(email_results) == 1
    assert email_results[0]["status"] == "error"
    assert "boom" in email_results[0]["message"]
