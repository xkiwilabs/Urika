"""Tests for the shared formatting helpers in notifications/formatting.py."""

from urika.notifications.events import (
    CANONICAL_EVENT_TYPES,
    EVENT_METADATA,
    NotificationEvent,
)
from urika.notifications.formatting import (
    format_event_emoji,
    format_event_label,
    format_event_summary_line,
)


def test_emoji_for_every_canonical_event_uses_metadata():
    for evt_type in CANONICAL_EVENT_TYPES:
        event = NotificationEvent(event_type=evt_type, project_name="p", summary="s")
        assert format_event_emoji(event) == EVENT_METADATA[evt_type].emoji


def test_emoji_for_non_canonical_event_uses_default():
    event = NotificationEvent(event_type="unknown_event", project_name="p", summary="s")
    assert format_event_emoji(event) == "ℹ️"
    assert format_event_emoji(event, default="X") == "X"


def test_label_for_every_canonical_event_uses_metadata():
    for evt_type in CANONICAL_EVENT_TYPES:
        event = NotificationEvent(event_type=evt_type, project_name="p", summary="s")
        assert format_event_label(event) == EVENT_METADATA[evt_type].label


def test_label_for_non_canonical_event_titlecases():
    event = NotificationEvent(event_type="some_new_event", project_name="p", summary="s")
    assert format_event_label(event) == "Some New Event"


def test_summary_line_combines_emoji_label_summary():
    event = NotificationEvent(
        event_type="experiment_completed",
        project_name="p",
        summary="all 5 runs passed",
    )
    line = format_event_summary_line(event)
    assert "\U0001f3c1" in line  # 🏁
    assert "Experiment Completed" in line
    assert "all 5 runs passed" in line
    assert "—" in line  # em dash separator
