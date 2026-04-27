"""Tests for the Telegram notification channel formatting."""

from __future__ import annotations


def test_telegram_formats_every_canonical_event_with_emoji_not_default():
    """Every canonical event must produce its EVENT_METADATA emoji, not the 🔔 fallback."""
    from urika.notifications.events import (
        CANONICAL_EVENT_TYPES,
        EVENT_METADATA,
        NotificationEvent,
    )
    from urika.notifications.telegram_channel import TelegramChannel

    for evt_type in CANONICAL_EVENT_TYPES:
        event = NotificationEvent(
            event_type=evt_type,
            project_name="p",
            summary="s",
            priority="high",  # force the high-priority format path
        )
        text = TelegramChannel._format_message(event)
        expected_emoji = EVENT_METADATA[evt_type].emoji
        assert expected_emoji in text, (
            f"{evt_type} message missing expected emoji {expected_emoji!r}: {text!r}"
        )
        # The bare-fallback bell must not appear unless it is the canonical emoji.
        if expected_emoji != "\U0001f514":
            assert "\U0001f514" not in text, (
                f"{evt_type} fell through to default 🔔 emoji: {text!r}"
            )
