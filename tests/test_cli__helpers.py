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


class _FakeOpener:
    """Minimal stand-in for urllib's OpenerDirector returned by
    ``build_opener``. Lets tests inject a per-request behaviour."""

    def __init__(self, behaviour):
        self._behaviour = behaviour

    def open(self, req, timeout):
        return self._behaviour(req, timeout)


def _patch_opener(monkeypatch, behaviour) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *a, **kw: _FakeOpener(behaviour)
    )


def test_test_endpoint_treats_http_error_as_reachable(monkeypatch) -> None:
    """A server that returns 401/403/404 is reachable — the endpoint exists."""
    import urllib.error

    def behaviour(req, timeout):
        raise urllib.error.HTTPError(
            url=req.full_url, code=401, msg="Unauthorized", hdrs={}, fp=None
        )

    _patch_opener(monkeypatch, behaviour)
    assert _test_endpoint("http://example.invalid:11434") is True


def test_test_endpoint_treats_connection_failure_as_unreachable(monkeypatch) -> None:
    """DNS / refused / timeout means the endpoint is genuinely down."""
    import urllib.error

    def behaviour(req, timeout):
        raise urllib.error.URLError("Connection refused")

    _patch_opener(monkeypatch, behaviour)
    assert _test_endpoint("http://example.invalid:11434") is False


def test_test_endpoint_treats_2xx_as_reachable(monkeypatch) -> None:
    """The happy path: 2xx response means the endpoint is up."""

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def getcode(self) -> int:
            return 200

    _patch_opener(monkeypatch, lambda req, timeout: _FakeResponse())
    assert _test_endpoint("http://example.invalid:11434") is True


def test_probe_endpoint_bypasses_system_proxy(monkeypatch) -> None:
    """``_probe_endpoint`` must use a no-proxy opener — private
    endpoints (Tailscale, LAN, localhost) shouldn't be routed through
    HTTP_PROXY. This was the root cause of a "url error: str" failure
    where the user's corporate proxy couldn't reach a Tailscale IP."""
    import urllib.request

    captured = {}

    real_build_opener = urllib.request.build_opener

    def spy_build_opener(*handlers):
        captured["handlers"] = handlers
        return real_build_opener(*handlers)

    monkeypatch.setattr(urllib.request, "build_opener", spy_build_opener)

    from urika.cli._helpers import _probe_endpoint

    # Behaviour doesn't matter — we just want to verify the opener
    # was built with a ProxyHandler({}).
    _probe_endpoint("http://example.invalid:11434")
    handlers = captured.get("handlers", ())
    assert any(
        isinstance(h, urllib.request.ProxyHandler) and h.proxies == {}
        for h in handlers
    ), f"expected a ProxyHandler({{}}) in handlers, got {handlers!r}"
