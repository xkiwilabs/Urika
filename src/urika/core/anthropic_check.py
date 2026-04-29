"""Verify an Anthropic API key works against api.anthropic.com.

Used by both ``urika config api-key --test`` (CLI) and the dashboard's
``POST /api/settings/test-anthropic-key`` endpoint. Kept self-contained
on the stdlib (``urllib``) so the test still works even when the
``anthropic`` SDK install is broken.

Per Anthropic Consumer Terms §3.7 and the April 2026 Agent SDK
clarification, Urika authenticates the Agent SDK with an API key —
NOT a Pro/Max OAuth token. Verifying the key here lets users confirm
that (a) the key is set, (b) Anthropic accepts it, and (c) Urika will
authenticate via this key rather than a subscription.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

# Cheapest + fastest Anthropic model. The test prompt is intentionally
# tiny (~8 input tokens) and ``max_tokens=5`` caps the output, so the
# whole verification round-trip costs roughly a hundredth of a cent.
_TEST_MODEL = "claude-haiku-4-5"
_TEST_URL = "https://api.anthropic.com/v1/messages"
_TEST_TIMEOUT_SEC = 10


def verify_anthropic_api_key(key: str) -> tuple[bool, str]:
    """Send a minimal POST to ``/v1/messages`` and report the result.

    Returns ``(ok, message)``. ``message`` is short and human-readable,
    suitable for direct display in CLI output or a JSON response body.

    Errors are mapped to actionable messages:

    * 401 → key invalid or revoked
    * 429 → rate limited or over the spend cap
    * 400 → bad request (passed through from Anthropic)
    * other HTTP / network → generic error string

    The function never raises; all exceptions are caught and returned
    as ``(False, message)``.
    """
    payload = {
        "model": _TEST_MODEL,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": "Reply with one word: ok"}],
    }
    req = urllib.request.Request(
        _TEST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TEST_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read())
        # Defensive content extraction — schema is well-known but we
        # don't want a one-off shape surprise to crash the test path.
        content = body.get("content", []) or []
        text = ""
        if content and isinstance(content[0], dict):
            text = content[0].get("text", "") or ""
        model = body.get("model", "?")
        return (
            True,
            f"key authenticated; model={model}; reply={text.strip()!r}",
        )
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
            err_msg = (
                err_body.get("error", {}).get("message", str(e))
                if isinstance(err_body, dict)
                else str(e)
            )
        except Exception:
            err_msg = str(e)
        if e.code == 401:
            return (
                False,
                f"401 unauthorized — key is invalid or revoked. ({err_msg})",
            )
        if e.code == 429:
            return (
                False,
                f"429 rate limited or over spend cap. ({err_msg})",
            )
        if e.code == 400:
            return (False, f"400 bad request — {err_msg}")
        return (False, f"HTTP {e.code} — {err_msg}")
    except urllib.error.URLError as e:
        return (False, f"network error: {e.reason}")
    except Exception as e:  # noqa: BLE001 — last-ditch catch for the test path.
        return (False, f"unexpected error: {type(e).__name__}: {e}")
