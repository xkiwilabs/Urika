"""Tests for urika.cli._helpers — the internal CLI helper module.

Distinct from tests/test_cli_helpers.py which tests the legacy
urika.cli_helpers module (no underscore). Keep them separate.
"""

from __future__ import annotations

import re
import time

from urika.cli._helpers import _agent_run_start


def test_agent_run_start_returns_int_ms_and_iso_string() -> None:
    start_ms, start_iso = _agent_run_start()
    assert isinstance(start_ms, int)
    assert start_ms > 0
    # ISO 8601 with timezone — should parse back trivially.
    assert isinstance(start_iso, str)
    # Loose format check: YYYY-MM-DDTHH:MM:SS... with +/- timezone marker.
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", start_iso), start_iso


def test_agent_run_start_ms_is_monotonic() -> None:
    """start_ms is monotonic ms since process start — each call should be later
    than the previous, so elapsed-ms math works."""
    first, _ = _agent_run_start()
    time.sleep(0.01)
    second, _ = _agent_run_start()
    assert second > first
    assert second - first >= 5  # at least 5ms elapsed
