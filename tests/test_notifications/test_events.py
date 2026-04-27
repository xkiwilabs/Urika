"""Tests for notification event creation."""

from __future__ import annotations

from datetime import datetime, timezone

from urika.notifications.events import (
    CANONICAL_EVENT_TYPES,
    EVENT_METADATA,
    NotificationEvent,
)


class TestNotificationEvent:
    def test_create_event(self):
        """Basic creation with required fields."""
        event = NotificationEvent(
            event_type="criteria_met",
            project_name="my-project",
            summary="Target metric reached",
        )
        assert event.event_type == "criteria_met"
        assert event.project_name == "my-project"
        assert event.summary == "Target metric reached"

    def test_defaults(self):
        """Priority defaults to 'medium', timestamp auto-set, experiment_id empty."""
        before = datetime.now(timezone.utc).isoformat()
        event = NotificationEvent(
            event_type="turn_started",
            project_name="proj",
            summary="Turn 1/5",
        )
        after = datetime.now(timezone.utc).isoformat()

        assert event.priority == "medium"
        assert event.experiment_id == ""
        assert isinstance(event.details, dict)
        assert len(event.details) == 0
        # Timestamp should be between before and after
        assert before <= event.timestamp <= after

    def test_details_dict(self):
        """Can pass details dict with metrics etc."""
        details = {"metrics": {"rmse": 0.42, "r2": 0.87}, "method": "random_forest"}
        event = NotificationEvent(
            event_type="run_recorded",
            project_name="proj",
            summary="Recorded run",
            details=details,
        )
        assert event.details["metrics"]["rmse"] == 0.42
        assert event.details["method"] == "random_forest"


def test_canonical_event_set_covers_all_emitters():
    """Every event_type emitted by the codebase must be canonical."""
    expected = {
        "experiment_started",
        "experiment_completed",
        "experiment_failed",
        "experiment_paused",
        "experiment_stopped",
        "meta_completed",
        "meta_paused",
        "criteria_met",
        "paused",   # legacy from on_progress mapper — keep for back-compat
        "test",     # used by --test sends
    }
    assert expected.issubset(CANONICAL_EVENT_TYPES)


def test_event_metadata_has_emoji_priority_label_for_each():
    for evt in CANONICAL_EVENT_TYPES:
        meta = EVENT_METADATA.get(evt)
        assert meta is not None, f"missing metadata for {evt}"
        assert meta.get("emoji"), f"missing emoji for {evt}"
        assert meta.get("priority") in {"low", "medium", "high"}
        assert meta.get("label"), f"missing label for {evt}"
