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
