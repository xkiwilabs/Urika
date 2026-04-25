"""Jinja filters for the dashboard templates."""

from __future__ import annotations

_VALID_TAG_STATUSES = {"running", "completed", "pending", "paused", "failed"}


def humanize(name: str | None) -> str:
    """Turn 'exp-001-baseline' into 'Exp 001 Baseline'.

    Replaces '-' and '_' with spaces and title-cases each word.
    Numeric segments are kept as-is. Returns '' for None/empty.
    """
    if not name:
        return ""
    cleaned = name.replace("-", " ").replace("_", " ")
    return " ".join(w.capitalize() if w[:1].isalpha() else w for w in cleaned.split())


def tag_status(status: str | None) -> str:
    """Lowercase + sanitize status for use in CSS modifier classes.

    Maps any input to one of the supported ``.tag--*`` modifiers
    ({running, completed, pending, paused, failed}). Falls back to
    ``"pending"`` for unknown / empty values so status pills always
    pick a defined color rule rather than an undefined modifier.
    """
    if not status:
        return "pending"
    s = status.lower().strip()
    return s if s in _VALID_TAG_STATUSES else "pending"
