"""Notification event types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


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


Priority = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class EventMetadata:
    """Rendering metadata for a canonical event type."""

    emoji: str
    priority: Priority
    label: str


# Canonical event-type vocabulary. Every event_type emitted anywhere in the
# codebase must appear here; channels and the bus mapper read EVENT_METADATA
# below for consistent emoji/priority/label rendering across destinations.
EVENT_METADATA: dict[str, EventMetadata] = {
    "experiment_started": EventMetadata(
        emoji="🚀", priority="medium", label="Experiment Started"
    ),
    "experiment_completed": EventMetadata(
        emoji="🏁", priority="high", label="Experiment Completed"
    ),
    "experiment_failed": EventMetadata(
        emoji="❌", priority="high", label="Experiment Failed"
    ),
    "experiment_paused": EventMetadata(
        emoji="⏸", priority="medium", label="Experiment Paused"
    ),
    "experiment_stopped": EventMetadata(
        emoji="⏹", priority="medium", label="Experiment Stopped"
    ),
    "meta_completed": EventMetadata(
        emoji="🏁", priority="high", label="Autonomous Run Complete"
    ),
    "meta_paused": EventMetadata(
        emoji="⏸", priority="medium", label="Autonomous Run Paused"
    ),
    "criteria_met": EventMetadata(emoji="✅", priority="high", label="Criteria Met"),
    # legacy alias from the on_progress mapper — keep for back-compat;
    # can be collapsed once callers migrate to the explicit experiment_*/meta_* events.
    "paused": EventMetadata(emoji="⏸", priority="medium", label="Paused"),
    "test": EventMetadata(emoji="🔔", priority="medium", label="Test Notification"),
}

# Derived from EVENT_METADATA so the two structures cannot drift.
CANONICAL_EVENT_TYPES: frozenset[str] = frozenset(EVENT_METADATA)
