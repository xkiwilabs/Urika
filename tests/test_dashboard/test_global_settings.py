"""Tests for the global settings page and PUT /api/settings."""

from __future__ import annotations


def test_global_settings_page_returns_200_and_renders_form(settings_client):
    r = settings_client.get("/settings")
    assert r.status_code == 200
    body = r.text
    for field in (
        "default_privacy_mode",
        "default_endpoint_url",
        "default_endpoint_key_env",
        "default_audience",
        "default_max_turns",
    ):
        assert f'name="{field}"' in body
    assert 'hx-put="/api/settings"' in body


def test_global_settings_put_writes_settings_toml(settings_client, tmp_path):
    r = settings_client.put(
        "/api/settings",
        data={
            "default_privacy_mode": "private",
            "default_endpoint_url": "http://localhost:11434",
            "default_endpoint_key_env": "MY_KEY",
            "default_audience": "novice",
            "default_max_turns": "20",
        },
    )
    assert r.status_code == 200
    import tomllib
    settings_path = tmp_path / "home" / "settings.toml"
    assert settings_path.exists()
    s = tomllib.loads(settings_path.read_text())
    assert s["privacy"]["mode"] == "private"
    assert s["privacy"]["endpoints"]["private"]["base_url"] == "http://localhost:11434"
    assert s["privacy"]["endpoints"]["private"]["api_key_env"] == "MY_KEY"
    assert s["preferences"]["audience"] == "novice"
    assert s["preferences"]["max_turns_per_experiment"] == 20


def test_global_settings_put_returns_html_fragment_by_default(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "default_privacy_mode": "open",
            "default_endpoint_url": "",
            "default_endpoint_key_env": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    assert "Saved" in r.text


def test_global_settings_put_returns_json_when_requested(settings_client):
    r = settings_client.put(
        "/api/settings",
        headers={"accept": "application/json"},
        data={
            "default_privacy_mode": "open",
            "default_endpoint_url": "",
            "default_endpoint_key_env": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["default_max_turns"] == 10


def test_global_settings_put_invalid_audience_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "default_privacy_mode": "open",
            "default_endpoint_url": "",
            "default_endpoint_key_env": "",
            "default_audience": "junior",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_invalid_max_turns_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "default_privacy_mode": "open",
            "default_endpoint_url": "",
            "default_endpoint_key_env": "",
            "default_audience": "expert",
            "default_max_turns": "-1",
        },
    )
    assert r.status_code == 422
