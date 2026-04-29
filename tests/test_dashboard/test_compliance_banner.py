"""Compliance banner on the global Settings page.

The banner surfaces when ``ANTHROPIC_API_KEY`` is unset in the dashboard
process environment, citing Anthropic Consumer Terms §3.7 and the April
2026 Agent SDK clarification. It hides when the key is configured.
"""

from __future__ import annotations


def test_banner_renders_when_api_key_unset(settings_client, monkeypatch):
    """No ANTHROPIC_API_KEY → compliance banner appears on /settings."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    body = settings_client.get("/settings").text
    assert "ANTHROPIC_API_KEY not set" in body
    assert "Consumer Terms" in body
    # Banner links to the canonical sources / setup paths.
    assert "console.anthropic.com" in body
    assert "urika config api-key" in body


def test_banner_hidden_when_api_key_set(settings_client, monkeypatch):
    """ANTHROPIC_API_KEY set → banner does not render."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-key")

    body = settings_client.get("/settings").text
    assert "ANTHROPIC_API_KEY not set" not in body
    # The settings form itself should still render.
    assert 'hx-put="/api/settings"' in body


def test_positive_indicator_shows_when_key_configured(settings_client, monkeypatch):
    """Key set → positive ✓ indicator + Test API key button appear."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-key")

    body = settings_client.get("/settings").text
    assert "ANTHROPIC_API_KEY configured" in body
    assert "Test API key" in body
    # Wires to the new endpoint.
    assert "/api/settings/test-anthropic-key" in body


def test_positive_indicator_hidden_when_key_unset(settings_client, monkeypatch):
    """Key unset → positive indicator does not render (warning banner does)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    body = settings_client.get("/settings").text
    assert "ANTHROPIC_API_KEY configured" not in body


# ---- POST /api/settings/test-anthropic-key --------------------------------


def test_test_anthropic_key_endpoint_returns_failure_when_no_key(
    settings_client, monkeypatch
):
    """Endpoint with no key set → ok=False + clear message, status 200."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Stub load_secrets so the test doesn't pull from the dev's real
    # ~/.urika/secrets.env on disk.
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)

    resp = settings_client.post("/api/settings/test-anthropic-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "ANTHROPIC_API_KEY is not set" in body["message"]


def test_test_anthropic_key_endpoint_returns_result_from_check_module(
    settings_client, monkeypatch
):
    """Endpoint with key set → delegates to anthropic_check + returns its result."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-good")
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)
    monkeypatch.setattr(
        "urika.core.anthropic_check.verify_anthropic_api_key",
        lambda key: (True, f"got key={key[:7]}..."),
    )

    resp = settings_client.post("/api/settings/test-anthropic-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "got key=sk-ant-" in body["message"]


def test_test_anthropic_key_endpoint_surfaces_check_module_failure(
    settings_client, monkeypatch
):
    """When the check module says ok=False, the endpoint passes that through."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-bad")
    monkeypatch.setattr("urika.core.secrets.load_secrets", lambda: None)
    monkeypatch.setattr(
        "urika.core.anthropic_check.verify_anthropic_api_key",
        lambda key: (False, "401 unauthorized — key is invalid or revoked."),
    )

    resp = settings_client.post("/api/settings/test-anthropic-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "401" in body["message"]
