"""Shared formatting helpers for notification channels.

Channels (Slack, Telegram) used to maintain their own event-type → emoji and
event-type → label maps in parallel. After Phase A unified the canonical
vocabulary in events.py:EVENT_METADATA, those lookups can share a single
implementation. Channel-specific structure (Slack Block Kit, Telegram HTML)
stays in the channel; only the per-event lookups move here.
"""

from __future__ import annotations

from urika.notifications.events import EVENT_METADATA, NotificationEvent

_DEFAULT_EMOJI = "ℹ️"  # ℹ️


def format_event_emoji(event: NotificationEvent, default: str = _DEFAULT_EMOJI) -> str:
    """Return the canonical emoji for *event*'s type, or *default* if unknown."""
    meta = EVENT_METADATA.get(event.event_type)
    return meta.emoji if meta else default


def format_event_label(event: NotificationEvent) -> str:
    """Return a human-readable label.

    Canonical event_types use their EVENT_METADATA label; non-canonical
    fall back to a title-cased version of the raw event_type.
    """
    meta = EVENT_METADATA.get(event.event_type)
    if meta:
        return meta.label
    return event.event_type.replace("_", " ").title()


def format_event_summary_line(event: NotificationEvent) -> str:
    """One-line "{emoji} {label} — {summary}" suitable for compact channels."""
    emoji = format_event_emoji(event)
    label = format_event_label(event)
    return f"{emoji} {label} — {event.summary}"
