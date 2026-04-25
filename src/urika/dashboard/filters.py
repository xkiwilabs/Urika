"""Jinja filters for the dashboard templates."""

from __future__ import annotations


def humanize(name: str | None) -> str:
    """Turn 'exp-001-baseline' into 'Exp 001 Baseline'.

    Replaces '-' and '_' with spaces and title-cases each word.
    Numeric segments are kept as-is. Returns '' for None/empty.
    """
    if not name:
        return ""
    cleaned = name.replace("-", " ").replace("_", " ")
    return " ".join(w.capitalize() if w[:1].isalpha() else w for w in cleaned.split())
