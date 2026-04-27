"""Tests for the Telegram notification channel formatting."""

from __future__ import annotations


def test_telegram_routes_canonical_events_by_metadata_priority():
    """Canonical event_types route through _format_message based on EVENT_METADATA."""
    from urika.notifications.events import (
        CANONICAL_EVENT_TYPES,
        EVENT_METADATA,
        NotificationEvent,
    )
    from urika.notifications.telegram_channel import TelegramChannel

    for evt_type in CANONICAL_EVENT_TYPES:
        event = NotificationEvent(
            event_type=evt_type,
            project_name="proj",
            summary="summary text",
        )
        text = TelegramChannel._format_message(event)
        meta = EVENT_METADATA[evt_type]
        if meta.priority == "high":
            # _format_high is invoked → emoji + label appear
            assert meta.emoji in text, (
                f"high-priority {evt_type} missing emoji {meta.emoji!r} in {text!r}"
            )
        else:
            # _format_default is invoked → minimal one-liner
            assert "proj" in text
            assert "summary text" in text
