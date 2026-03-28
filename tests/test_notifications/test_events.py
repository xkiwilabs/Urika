"""Tests for notification event creation."""

from __future__ import annotations

from datetime import datetime, timezone

from urika.notifications.events import NotificationEvent


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
