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
