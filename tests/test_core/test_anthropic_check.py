"""Unit tests for ``urika.core.anthropic_check``.

The module is the single source of truth for "does this Anthropic API
key actually work" — used by both the CLI's ``urika config api-key
--test`` path and the dashboard's POST /api/settings/test-anthropic-key
endpoint.

All tests mock ``urllib.request.urlopen`` so nothing leaves the box.
The function never raises: every error path (401, 429, 400, network,
unexpected) must be returned as ``(False, message)``.
"""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from urika.core.anthropic_check import verify_anthropic_api_key


# ---- Success path --------------------------------------------------------


def _fake_response(payload: dict) -> MagicMock:
    """Build a context-manager-shaped mock for urllib.request.urlopen."""
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=resp)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_returns_ok_when_anthropic_responds_200() -> None:
    payload = {
        "model": "claude-haiku-4-5",
        "content": [{"type": "text", "text": "ok"}],
    }
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen",
        return_value=_fake_response(payload),
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-fake")
    assert ok is True
    assert "claude-haiku-4-5" in msg
    assert "ok" in msg


def test_returns_ok_even_with_empty_content_array() -> None:
    """Defensive content extraction — never crash on shape surprises."""
    payload = {"model": "claude-haiku-4-5", "content": []}
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen",
        return_value=_fake_response(payload),
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-fake")
    assert ok is True
    assert "claude-haiku-4-5" in msg


# ---- HTTP error paths ----------------------------------------------------


def _http_error(code: int, body: dict | str) -> urllib.error.HTTPError:
    raw = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body.encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api.anthropic.com/v1/messages",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(raw),
    )


def test_401_maps_to_invalid_or_revoked_message() -> None:
    err = _http_error(
        401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}
    )
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen", side_effect=err
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-bad")
    assert ok is False
    assert "401" in msg
    assert "invalid" in msg.lower() or "revoked" in msg.lower()


def test_429_maps_to_rate_limited_message() -> None:
    err = _http_error(
        429, {"error": {"type": "rate_limit_error", "message": "rate limit exceeded"}}
    )
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen", side_effect=err
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-x")
    assert ok is False
    assert "429" in msg
    assert "rate limit" in msg.lower() or "spend" in msg.lower()


def test_400_passes_through_anthropic_message() -> None:
    err = _http_error(
        400, {"error": {"type": "invalid_request_error", "message": "bad model"}}
    )
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen", side_effect=err
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-x")
    assert ok is False
    assert "400" in msg
    assert "bad model" in msg


def test_other_http_codes_surface_status_and_message() -> None:
    err = _http_error(503, {"error": {"message": "service down"}})
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen", side_effect=err
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-x")
    assert ok is False
    assert "503" in msg


def test_http_error_with_unparseable_body_falls_back_to_str() -> None:
    err = _http_error(500, "<html>oops</html>")
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen", side_effect=err
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-x")
    assert ok is False
    assert "500" in msg


# ---- Network / unexpected paths ------------------------------------------


def test_network_error_is_caught() -> None:
    err = urllib.error.URLError("name resolution failed")
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen", side_effect=err
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-x")
    assert ok is False
    assert "network error" in msg
    assert "name resolution failed" in msg


def test_unexpected_exception_is_caught() -> None:
    """Last-ditch catch — guarantees the function never raises."""
    with patch(
        "urika.core.anthropic_check.urllib.request.urlopen",
        side_effect=RuntimeError("boom"),
    ):
        ok, msg = verify_anthropic_api_key("sk-ant-x")
    assert ok is False
    assert "unexpected error" in msg
    assert "RuntimeError" in msg
