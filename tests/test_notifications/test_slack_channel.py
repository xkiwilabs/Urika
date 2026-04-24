"""Tests for the Slack notification channel authorization allowlist."""

from __future__ import annotations

import logging
from typing import Any

from urika.notifications.slack_channel import SlackChannel


def _slack_config(
    allowed_channels: list[str] | None = None,
    allowed_users: list[str] | None = None,
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "channel": "#urika",
        "bot_token_env": "",
        "app_token_env": "",
    }
    if allowed_channels is not None:
        cfg["allowed_channels"] = allowed_channels
    if allowed_users is not None:
        cfg["allowed_users"] = allowed_users
    return cfg


def _make_channel(
    allowed_channels: list[str] | None = None,
    allowed_users: list[str] | None = None,
) -> SlackChannel:
    return SlackChannel(_slack_config(allowed_channels, allowed_users))


# ---------------------------------------------------------------------------
# _is_authorized
# ---------------------------------------------------------------------------


def test_is_authorized_allows_all_when_no_allowlist():
    channel = _make_channel()
    assert (
        channel._is_authorized({"channel": {"id": "CANY"}, "user": {"id": "UANY"}})
        is True
    )


def test_is_authorized_allows_all_when_no_allowlist_even_with_empty_payload():
    channel = _make_channel()
    assert channel._is_authorized({}) is True


def test_is_authorized_blocks_non_allowlisted_channel():
    channel = _make_channel(allowed_channels=["CALLOWED"])
    assert (
        channel._is_authorized({"channel": {"id": "COTHER"}, "user": {"id": "U1"}})
        is False
    )


def test_is_authorized_blocks_non_allowlisted_user():
    channel = _make_channel(allowed_users=["UALLOWED"])
    assert (
        channel._is_authorized({"channel": {"id": "C1"}, "user": {"id": "UOTHER"}})
        is False
    )


def test_is_authorized_allows_matching_channel_and_user():
    channel = _make_channel(
        allowed_channels=["CALLOWED"], allowed_users=["UALLOWED"]
    )
    assert (
        channel._is_authorized(
            {"channel": {"id": "CALLOWED"}, "user": {"id": "UALLOWED"}}
        )
        is True
    )


def test_is_authorized_allows_only_channel_match_when_users_none():
    channel = _make_channel(allowed_channels=["CALLOWED"])
    assert (
        channel._is_authorized(
            {"channel": {"id": "CALLOWED"}, "user": {"id": "UANY"}}
        )
        is True
    )


def test_is_authorized_allows_only_user_match_when_channels_none():
    channel = _make_channel(allowed_users=["UALLOWED"])
    assert (
        channel._is_authorized(
            {"channel": {"id": "CANY"}, "user": {"id": "UALLOWED"}}
        )
        is True
    )


def test_is_authorized_fail_closed_on_missing_channel_id():
    channel = _make_channel(allowed_channels=["CALLOWED"])
    # allowlist set but payload has no channel field → unauthorized
    assert channel._is_authorized({"user": {"id": "U1"}}) is False


def test_is_authorized_fail_closed_on_missing_user_id():
    channel = _make_channel(allowed_users=["UALLOWED"])
    # allowlist set but payload has no user field → unauthorized
    assert channel._is_authorized({"channel": {"id": "C1"}}) is False


def test_is_authorized_extracts_channel_from_event_fallback():
    channel = _make_channel(allowed_channels=["CALLOWED"])
    # Message-event shape: channel id lives at payload["event"]["channel"]
    assert (
        channel._is_authorized(
            {"event": {"channel": "CALLOWED", "user": "U1"}}
        )
        is True
    )


def test_is_authorized_extracts_user_from_event_fallback():
    channel = _make_channel(allowed_users=["UALLOWED"])
    assert (
        channel._is_authorized(
            {"event": {"channel": "C1", "user": "UALLOWED"}}
        )
        is True
    )


def test_is_authorized_event_fallback_blocks_non_allowlisted():
    channel = _make_channel(allowed_channels=["CALLOWED"])
    assert (
        channel._is_authorized(
            {"event": {"channel": "COTHER", "user": "U1"}}
        )
        is False
    )


# ---------------------------------------------------------------------------
# Init warning
# ---------------------------------------------------------------------------


def test_warning_logged_when_no_allowlist_set(caplog):
    caplog.set_level(logging.WARNING, logger="urika.notifications.slack_channel")
    _make_channel()
    assert any(
        "without allowed_channels or allowed_users" in r.message
        for r in caplog.records
    )


def test_no_warning_when_allowed_channels_set(caplog):
    caplog.set_level(logging.WARNING, logger="urika.notifications.slack_channel")
    _make_channel(allowed_channels=["C1"])
    assert not any(
        "without allowed_channels" in r.message for r in caplog.records
    )


def test_no_warning_when_allowed_users_set(caplog):
    caplog.set_level(logging.WARNING, logger="urika.notifications.slack_channel")
    _make_channel(allowed_users=["U1"])
    assert not any(
        "without allowed_channels" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Instance attributes
# ---------------------------------------------------------------------------


def test_default_allowlists_are_none():
    channel = _make_channel()
    assert channel._allowed_channels is None
    assert channel._allowed_users is None


def test_allowlists_stored_as_attrs():
    channel = _make_channel(
        allowed_channels=["C1", "C2"], allowed_users=["U1"]
    )
    assert channel._allowed_channels == ["C1", "C2"]
    assert channel._allowed_users == ["U1"]


# ---------------------------------------------------------------------------
# Realistic payload shapes (handler flow)
# ---------------------------------------------------------------------------


def test_is_authorized_realistic_button_click_payload_allowed():
    """Block Kit button-click payloads have channel.id + user.id at top level."""
    channel = _make_channel(
        allowed_channels=["CALLOWED"], allowed_users=["UALLOWED"]
    )
    button_payload = {
        "type": "block_actions",
        "user": {"id": "UALLOWED", "name": "alice"},
        "channel": {"id": "CALLOWED", "name": "urika"},
        "actions": [{"action_id": "pause", "type": "button"}],
    }
    assert channel._is_authorized(button_payload) is True


def test_is_authorized_realistic_button_click_payload_blocked():
    channel = _make_channel(allowed_users=["UALLOWED"])
    button_payload = {
        "type": "block_actions",
        "user": {"id": "UATTACKER", "name": "mallory"},
        "channel": {"id": "C1", "name": "general"},
        "actions": [{"action_id": "stop", "type": "button"}],
    }
    assert channel._is_authorized(button_payload) is False


def test_is_authorized_realistic_message_event_payload_allowed():
    """Event-API message payloads nest channel/user as string ids under event."""
    channel = _make_channel(
        allowed_channels=["CALLOWED"], allowed_users=["UALLOWED"]
    )
    event_payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "CALLOWED",
            "user": "UALLOWED",
            "text": "/status",
        },
    }
    assert channel._is_authorized(event_payload) is True


def test_is_authorized_realistic_message_event_payload_blocked():
    channel = _make_channel(allowed_channels=["CALLOWED"])
    event_payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel": "COTHER",
            "user": "U1",
            "text": "/stop",
        },
    }
    assert channel._is_authorized(event_payload) is False
