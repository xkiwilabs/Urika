"""Tests for POST /api/settings/test-endpoint.

Phase P3 of the UI polish + CLI parity plan.  The dashboard's Privacy
tab needs a "Test" button that probes a private model endpoint without
firing a real agent run.  The endpoint reuses
``urika.cli._helpers._test_endpoint`` (3 s timeout) and never persists
anything to ``settings.toml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    """A dashboard with a tmp ``URIKA_HOME`` so we can assert that the
    test-endpoint POST never writes ``settings.toml``."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_returns_422_when_base_url_missing(client):
    """POST with no ``base_url`` field at all -> 422."""
    r = client.post("/api/settings/test-endpoint", data={})
    assert r.status_code == 422
    assert "base_url is required" in r.text


def test_returns_422_when_base_url_blank(client):
    """POST with ``base_url=""`` (whitespace-only) -> 422."""
    r = client.post(
        "/api/settings/test-endpoint",
        data={"base_url": "   "},
    )
    assert r.status_code == 422
    assert "base_url is required" in r.text


def test_returns_reachable_true_when_endpoint_responds(client, monkeypatch):
    """When the helper returns True, the response says reachable + OK."""
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (True, "OK"),
    )
    r = client.post(
        "/api/settings/test-endpoint",
        data={"base_url": "http://localhost:11434"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is True
    assert body["details"] == "OK"


def test_returns_reachable_false_when_endpoint_does_not_respond(client, monkeypatch):
    """When the probe returns False, response surfaces the failure
    reason from the helper (e.g. 'connection refused')."""
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (False, "connection refused"),
    )
    r = client.post(
        "/api/settings/test-endpoint",
        data={"base_url": "http://localhost:11434"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False
    assert body["details"] == "connection refused"


def test_returns_reachable_false_when_helper_raises(client, monkeypatch):
    """When ``_probe_endpoint`` raises, the response surfaces the
    exception's *type* but never its ``str(e)`` (which could carry
    creds embedded in a misconfigured proxy URL)."""
    secret = "supersecret-token-do-not-leak"

    def boom(url):
        raise RuntimeError(secret)

    monkeypatch.setattr("urika.cli._helpers._probe_endpoint", boom)
    r = client.post(
        "/api/settings/test-endpoint",
        data={"base_url": "http://localhost:11434"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False
    assert body["details"].startswith("error:")
    # The exception class name is fine; the message is NOT.
    assert "RuntimeError" in body["details"]
    assert secret not in body["details"]


def test_returns_api_key_set_true_when_env_var_set(client, monkeypatch):
    """``api_key_env`` pointing at an env var with a non-empty value
    -> ``api_key_set`` true."""
    monkeypatch.setenv("MY_KEY", "secret")
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (True, "OK"),
    )
    r = client.post(
        "/api/settings/test-endpoint",
        data={
            "base_url": "http://localhost:11434",
            "api_key_env": "MY_KEY",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_env"] == "MY_KEY"
    assert body["api_key_set"] is True


def test_returns_api_key_set_false_when_env_var_missing(client, monkeypatch):
    """``api_key_env`` pointing at a non-existent env var
    -> ``api_key_set`` false."""
    monkeypatch.delenv("MISSING_KEY", raising=False)
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (True, "OK"),
    )
    r = client.post(
        "/api/settings/test-endpoint",
        data={
            "base_url": "http://localhost:11434",
            "api_key_env": "MISSING_KEY",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_env"] == "MISSING_KEY"
    assert body["api_key_set"] is False


def test_returns_api_key_set_false_when_env_var_empty_string(client, monkeypatch):
    """An env var set to the empty string is treated as unset.  A
    whitespace-only value is also treated as unset."""
    monkeypatch.setenv("EMPTY_KEY", "")
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (True, "OK"),
    )
    r = client.post(
        "/api/settings/test-endpoint",
        data={
            "base_url": "http://localhost:11434",
            "api_key_env": "EMPTY_KEY",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_env"] == "EMPTY_KEY"
    assert body["api_key_set"] is False


def test_omits_api_key_check_when_no_env_specified(client, monkeypatch):
    """No ``api_key_env`` at all -> ``api_key_env: null,
    api_key_set: false`` (open endpoints don't need a key)."""
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (True, "OK"),
    )
    r = client.post(
        "/api/settings/test-endpoint",
        data={"base_url": "http://localhost:11434"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_env"] is None
    assert body["api_key_set"] is False


def test_does_not_persist_settings(client, monkeypatch, tmp_path):
    """A test POST must never touch ``~/.urika/settings.toml``."""
    monkeypatch.setattr(
        "urika.cli._helpers._probe_endpoint",
        lambda url: (True, "OK"),
    )
    settings_file = tmp_path / "home" / "settings.toml"
    assert not settings_file.exists()
    r = client.post(
        "/api/settings/test-endpoint",
        data={
            "base_url": "http://localhost:11434",
            "api_key_env": "MY_KEY",
        },
    )
    assert r.status_code == 200
    # No write side effect.
    assert not settings_file.exists()
