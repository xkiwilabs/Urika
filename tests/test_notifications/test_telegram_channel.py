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


def test_telegram_esc_escapes_html_metacharacters():
    from urika.notifications.telegram_channel import _esc

    assert _esc("a<b>&c") == "a&lt;b&gt;&amp;c"


def test_telegram_high_format_escapes_metric_values():
    """Metric VALUES must be HTML-escaped under parse_mode=HTML, not just keys
    (Task 2.5 B2 — an unescaped '<' would break Telegram's HTML parser)."""
    from urika.notifications.events import EVENT_METADATA, NotificationEvent
    from urika.notifications.telegram_channel import _format_high

    # Pick any high-priority canonical event type.
    high_type = next(
        t for t, m in EVENT_METADATA.items() if m.priority == "high"
    )
    event = NotificationEvent(
        event_type=high_type,
        project_name="proj",
        summary="done",
        details={"metrics": {"r2": "<0.5>"}},
    )
    text = _format_high(event)
    assert "r2: &lt;0.5&gt;" in text
    assert "<0.5>" not in text
