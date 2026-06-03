"""Tests for the dashboard provider-auth toggle (cross-surface parity).

The CLI exposes ``urika config anthropic|openai|google --mode ...`` which
writes ``[<provider>] auth = "..."`` to ``~/.urika/settings.toml``. This
test module pins:

  * The Models tab on ``/settings`` renders an Anthropic auth-mode
    <select> with two options (api_key + subscription).
  * ``POST /api/settings/provider-auth`` accepts ``provider`` +
    ``mode`` form fields and persists ``[<provider>] auth`` to
    settings.toml.
  * Subscription mode is rejected for openai / google with 400 (per
    CLI's UsageError, which is the canonical refusal of OpenAI Plus and
    Google AI Pro/Ultra subscription auth).
  * Invalid mode / provider returns 400.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path, auth_token=None)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Rendering — Models tab carries the auth-mode picker.
# ---------------------------------------------------------------------------


def test_models_tab_renders_anthropic_auth_select(settings_client: TestClient) -> None:
    """The Provider <select> on the Models tab pairs with an Anthropic
    auth-mode <select>. Both options must be present so the user can
    flip between API-key and subscription modes from the UI."""
    body = settings_client.get("/settings").text
    assert 'name="anthropic_auth"' in body
    # Both choices must be visible options.
    assert 'value="api_key"' in body
    assert 'value="subscription"' in body


def test_models_tab_mentions_claude_login_for_subscription(
    settings_client: TestClient,
) -> None:
    """The helper text next to the subscription option must tell users
    to run ``claude login`` first — otherwise switching modes silently
    breaks every experiment until they figure it out from the docs."""
    body = settings_client.get("/settings").text
    assert "claude login" in body


def test_models_tab_renders_existing_anthropic_auth(
    settings_client: TestClient, tmp_path: Path
) -> None:
    """When ``[anthropic] auth`` is already set in settings.toml, the
    matching radio/option must be pre-selected."""
    (tmp_path / "home" / "settings.toml").write_text(
        '[anthropic]\nauth = "subscription"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # The subscription option should be the selected one.
    assert (
        'value="subscription" selected' in body
        or 'selected value="subscription"' in body
    )


# ---------------------------------------------------------------------------
# POST endpoint — writes [<provider>] auth to settings.toml.
# ---------------------------------------------------------------------------


def test_post_anthropic_auth_api_key_persists(
    settings_client: TestClient, tmp_path: Path
) -> None:
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "anthropic", "mode": "api_key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "anthropic"
    assert body["mode"] == "api_key"

    s_path = tmp_path / "home" / "settings.toml"
    data = tomllib.loads(s_path.read_text(encoding="utf-8"))
    assert data["anthropic"]["auth"] == "api_key"


def test_post_anthropic_auth_subscription_persists(
    settings_client: TestClient, tmp_path: Path
) -> None:
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "anthropic", "mode": "subscription"},
    )
    assert r.status_code == 200
    s_path = tmp_path / "home" / "settings.toml"
    data = tomllib.loads(s_path.read_text(encoding="utf-8"))
    assert data["anthropic"]["auth"] == "subscription"


def test_post_openai_subscription_returns_400(
    settings_client: TestClient, tmp_path: Path
) -> None:
    """OpenAI Plus is a separate product from the API — refuse it the
    same way the CLI does."""
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "openai", "mode": "subscription"},
    )
    assert r.status_code == 400
    s_path = tmp_path / "home" / "settings.toml"
    if s_path.exists():
        data = tomllib.loads(s_path.read_text(encoding="utf-8"))
        assert (
            "openai" not in data or data.get("openai", {}).get("auth") != "subscription"
        )


def test_post_google_subscription_returns_400(
    settings_client: TestClient, tmp_path: Path
) -> None:
    """Google AI Pro/Ultra ToS forbid third-party SDK use — refuse it
    the same way the CLI does."""
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "google", "mode": "subscription"},
    )
    assert r.status_code == 400


def test_post_openai_api_key_persists(
    settings_client: TestClient, tmp_path: Path
) -> None:
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "openai", "mode": "api_key"},
    )
    assert r.status_code == 200
    s_path = tmp_path / "home" / "settings.toml"
    data = tomllib.loads(s_path.read_text(encoding="utf-8"))
    assert data["openai"]["auth"] == "api_key"


def test_post_google_api_key_persists(
    settings_client: TestClient, tmp_path: Path
) -> None:
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "google", "mode": "api_key"},
    )
    assert r.status_code == 200
    s_path = tmp_path / "home" / "settings.toml"
    data = tomllib.loads(s_path.read_text(encoding="utf-8"))
    assert data["google"]["auth"] == "api_key"


def test_post_invalid_provider_returns_400(settings_client: TestClient) -> None:
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "garbage", "mode": "api_key"},
    )
    assert r.status_code == 400


def test_post_invalid_mode_returns_400(settings_client: TestClient) -> None:
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "anthropic", "mode": "magic"},
    )
    assert r.status_code == 400


def test_post_preserves_unrelated_sections(
    settings_client: TestClient, tmp_path: Path
) -> None:
    """Writing the auth key must not blow away unrelated sections."""
    (tmp_path / "home" / "settings.toml").write_text(
        '[preferences]\naudience = "expert"\n\n'
        "[privacy.endpoints.private]\n"
        'base_url = "http://localhost:11434"\n',
        encoding="utf-8",
    )
    r = settings_client.post(
        "/api/settings/provider-auth",
        data={"provider": "anthropic", "mode": "subscription"},
    )
    assert r.status_code == 200
    s_path = tmp_path / "home" / "settings.toml"
    data = tomllib.loads(s_path.read_text(encoding="utf-8"))
    assert data["anthropic"]["auth"] == "subscription"
    assert data["preferences"]["audience"] == "expert"
    assert data["privacy"]["endpoints"]["private"]["base_url"] == (
        "http://localhost:11434"
    )
