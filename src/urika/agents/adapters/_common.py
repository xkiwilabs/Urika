"""Shared adapter tunables.

The stream timeout and bash-timeout cap were previously duplicated
per adapter (v0.7.1 review); a default change must now touch one place.
"""

from __future__ import annotations

import os


def agent_stream_timeout() -> float:
    """Seconds an SDK stream may stay silent before the adapter
    fails the call as transient. Env-tunable; read at call time so
    tests and operators can adjust without re-import.

    An invalid env value silently falls back to 600 — a bad setting
    must not crash the adapter at runtime.
    """
    try:
        return float(os.environ.get("URIKA_AGENT_STREAM_TIMEOUT", "600"))
    except (TypeError, ValueError):
        return 600.0


def bash_timeout_seconds(max_method_seconds: int | None) -> int:
    """Bash tool timeout: the project's max_method_seconds cap, else 600."""
    return max_method_seconds or 600
