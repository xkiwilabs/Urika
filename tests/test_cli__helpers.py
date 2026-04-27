"""Tests for urika.cli._helpers — the internal CLI helper module.

Distinct from tests/test_cli_helpers.py which tests the legacy
urika.cli_helpers module (no underscore). Keep them separate.
"""

from __future__ import annotations

import re
import time

from urika.cli._helpers import _agent_run_start, _test_endpoint


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


# ---- _test_endpoint reachability behaviour ----
# The helper must treat ANY HTTP response (including 401 / 403 / 404)
# as "reachable" — the server answered, so the endpoint exists. Only
# connection-level failures count as unreachable. This pins the fix
# for the bug where a working OpenAI-compatible endpoint that requires
# auth was being reported "Unreachable" because the unauthenticated
# probe got a 401.


def test_test_endpoint_treats_http_error_as_reachable(monkeypatch) -> None:
    """A server that returns 401/403/404 is reachable — the endpoint exists."""
    import urllib.error
    import urllib.request

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            url=req.full_url, code=401, msg="Unauthorized", hdrs={}, fp=None
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert _test_endpoint("http://example.invalid:11434") is True


def test_test_endpoint_treats_connection_failure_as_unreachable(monkeypatch) -> None:
    """DNS / refused / timeout means the endpoint is genuinely down."""
    import urllib.error
    import urllib.request

    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert _test_endpoint("http://example.invalid:11434") is False


def test_test_endpoint_treats_2xx_as_reachable(monkeypatch) -> None:
    """The happy path: 2xx response means the endpoint is up."""
    import urllib.request

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _FakeResponse())
    assert _test_endpoint("http://example.invalid:11434") is True
