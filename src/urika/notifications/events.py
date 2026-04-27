"""Notification event types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class NotificationEvent:
    """A notification to be dispatched to external channels."""

    event_type: str  # experiment_started, turn_completed, criteria_met, etc.
    project_name: str
    summary: str  # Human-readable one-liner
    experiment_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    priority: str = "medium"  # low, medium, high
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# Canonical event-type vocabulary. Every event_type emitted anywhere in the
# codebase must appear here; channels and the bus mapper read EVENT_METADATA
# below for consistent emoji/priority/label rendering across destinations.
CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({
    "experiment_started",
    "experiment_completed",
    "experiment_failed",
    "experiment_paused",
    "experiment_stopped",
    "meta_completed",
    "meta_paused",
    "criteria_met",
    "paused",
    "test",
})

EVENT_METADATA: dict[str, dict[str, str]] = {
    "experiment_started":   {"emoji": "🚀", "priority": "medium", "label": "Experiment Started"},
    "experiment_completed": {"emoji": "🏁", "priority": "high",   "label": "Experiment Completed"},
    "experiment_failed":    {"emoji": "❌", "priority": "high",   "label": "Experiment Failed"},
    "experiment_paused":    {"emoji": "⏸",  "priority": "medium", "label": "Experiment Paused"},
    "experiment_stopped":   {"emoji": "⏹",  "priority": "medium", "label": "Experiment Stopped"},
    "meta_completed":       {"emoji": "🏁", "priority": "high",   "label": "Autonomous Run Complete"},
    "meta_paused":          {"emoji": "⏸",  "priority": "medium", "label": "Autonomous Run Paused"},
    "criteria_met":         {"emoji": "✅", "priority": "high",   "label": "Criteria Met"},
    "paused":               {"emoji": "⏸",  "priority": "medium", "label": "Paused"},
    "test":                 {"emoji": "🔔", "priority": "medium", "label": "Test Notification"},
}
