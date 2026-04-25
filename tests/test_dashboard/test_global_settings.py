"""Tests for the global settings page and PUT /api/settings.

The page is a 4-tab layout (Privacy / Models / Preferences / Notifications)
that writes the full ~/.urika/settings.toml in a single PUT.
"""

from __future__ import annotations

import tomllib


# ---- Page rendering --------------------------------------------------------


def test_global_settings_page_returns_200_and_renders_form(settings_client):
    r = settings_client.get("/settings")
    assert r.status_code == 200
    body = r.text
    assert 'hx-put="/api/settings"' in body


def test_global_settings_page_has_four_tab_buttons(settings_client):
    """Page renders with 4 tabs: Privacy / Models / Preferences / Notifications."""
    body = settings_client.get("/settings").text
    for label in ("Privacy", "Models", "Preferences", "Notifications"):
        assert f">{label}</button>" in body, f"missing tab button: {label}"


def test_global_settings_uses_tabs_macro(settings_client):
    """The page uses the tabs macro from _macros.html (Alpine x-data scope)."""
    body = settings_client.get("/settings").text
    assert 'x-data="{ active:' in body
    assert "tab-button" in body


def test_global_settings_privacy_tab_has_three_mode_blocks(settings_client):
    """Privacy tab exposes inputs for open / private / hybrid configs."""
    body = settings_client.get("/settings").text
    # Mode picker
    assert 'name="privacy_mode"' in body
    # Open block
    assert 'name="privacy_open_model"' in body
    # Private block
    assert 'name="privacy_private_url"' in body
    assert 'name="privacy_private_key_env"' in body
    assert 'name="privacy_private_model"' in body
    # Hybrid block
    assert 'name="privacy_hybrid_cloud_model"' in body
    assert 'name="privacy_hybrid_private_url"' in body
    assert 'name="privacy_hybrid_private_key_env"' in body
    assert 'name="privacy_hybrid_private_model"' in body


def test_global_settings_models_tab_has_per_agent_rows(settings_client):
    """Models tab renders a row per known agent + a top-level model field."""
    body = settings_client.get("/settings").text
    assert 'name="runtime_model"' in body
    for agent in (
        "planning_agent",
        "task_agent",
        "evaluator",
        "advisor_agent",
        "tool_builder",
        "literature_agent",
        "presentation_agent",
        "report_agent",
        "project_builder",
        "data_agent",
        "finalizer",
    ):
        assert f'name="model[{agent}]"' in body
        assert f'name="endpoint[{agent}]"' in body


def test_global_settings_preferences_tab_has_expected_fields(settings_client):
    """Preferences tab exposes audience, max_turns, web_search, venv."""
    body = settings_client.get("/settings").text
    assert 'name="default_audience"' in body
    assert 'name="default_max_turns"' in body
    assert 'name="web_search"' in body
    assert 'name="venv"' in body


def test_global_settings_notifications_tab_has_channels(settings_client):
    """Notifications tab exposes per-channel enable + config fields."""
    body = settings_client.get("/settings").text
    # Email
    assert 'name="notifications_email_enabled"' in body
    assert 'name="notifications_email_from"' in body
    assert 'name="notifications_email_to"' in body
    assert 'name="notifications_email_smtp_host"' in body
    assert 'name="notifications_email_smtp_port"' in body
    # Slack
    assert 'name="notifications_slack_enabled"' in body
    assert 'name="notifications_slack_channel"' in body
    assert 'name="notifications_slack_token_env"' in body
    # Telegram
    assert 'name="notifications_telegram_enabled"' in body
    assert 'name="notifications_telegram_chat_id"' in body
    assert 'name="notifications_telegram_bot_token_env"' in body


# ---- Privacy tab round-trips -----------------------------------------------


def test_global_settings_put_private_mode_writes_endpoint(settings_client, tmp_path):
    """Mode=private with endpoint URL + model writes [privacy.endpoints.private]."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "private",
            "privacy_private_url": "http://localhost:11434",
            "privacy_private_key_env": "",
            "privacy_private_model": "qwen3",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["privacy"]["mode"] == "private"
    assert s["privacy"]["endpoints"]["private"]["base_url"] == "http://localhost:11434"
    assert s["runtime"]["model"] == "qwen3"


def test_global_settings_put_hybrid_mode_writes_both_blocks(settings_client, tmp_path):
    """Mode=hybrid writes cloud model + private endpoint config for data agents."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "hybrid",
            "privacy_hybrid_cloud_model": "claude-sonnet-4-5",
            "privacy_hybrid_private_url": "http://localhost:11434",
            "privacy_hybrid_private_key_env": "",
            "privacy_hybrid_private_model": "qwen3",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["privacy"]["mode"] == "hybrid"
    assert s["privacy"]["endpoints"]["private"]["base_url"] == "http://localhost:11434"
    assert s["runtime"]["model"] == "claude-sonnet-4-5"
    # Hybrid wires data_agent → private model
    assert s["runtime"]["models"]["data_agent"]["model"] == "qwen3"
    assert s["runtime"]["models"]["data_agent"]["endpoint"] == "private"


def test_global_settings_put_open_mode_writes_cloud_model(settings_client, tmp_path):
    """Mode=open uses the open_model dropdown for [runtime].model."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["privacy"]["mode"] == "open"
    assert s["runtime"]["model"] == "claude-sonnet-4-5"


def test_global_settings_put_private_missing_url_returns_422(settings_client):
    """Mode=private with no endpoint URL fails validation."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "private",
            "privacy_private_url": "",
            "privacy_private_model": "qwen3",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_private_missing_model_returns_422(settings_client):
    """Mode=private with no model fails validation."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "private",
            "privacy_private_url": "http://localhost:11434",
            "privacy_private_model": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_invalid_privacy_mode_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "bogus",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


# ---- Models tab round-trip --------------------------------------------------


def test_global_settings_put_per_agent_override_writes_runtime_models(
    settings_client, tmp_path
):
    """[runtime.models.<agent>] is populated from model[<agent>] form fields."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "model[task_agent]": "qwen3-coder",
            "endpoint[task_agent]": "private",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["runtime"]["models"]["task_agent"]["model"] == "qwen3-coder"
    assert s["runtime"]["models"]["task_agent"]["endpoint"] == "private"


def test_global_settings_put_runtime_model_override_writes_runtime_model(
    settings_client, tmp_path
):
    """runtime_model field sets [runtime].model directly."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_model": "claude-haiku-4-5",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    # runtime_model overrides whatever the privacy block computed
    assert s["runtime"]["model"] == "claude-haiku-4-5"


# ---- Preferences tab round-trip --------------------------------------------


def test_global_settings_put_preferences_writes_audience_and_max_turns(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "novice",
            "default_max_turns": "20",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["preferences"]["audience"] == "novice"
    assert s["preferences"]["max_turns_per_experiment"] == 20


def test_global_settings_put_preferences_writes_web_search_and_venv(
    settings_client, tmp_path
):
    """web_search and venv checkboxes round-trip as booleans."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "web_search": "on",
            "venv": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["preferences"]["web_search"] is True
    assert s["preferences"]["venv"] is True


def test_global_settings_put_preferences_unchecked_writes_false(
    settings_client, tmp_path
):
    """An unchecked checkbox arrives absent → field stored as False."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            # web_search and venv intentionally omitted
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["preferences"]["web_search"] is False
    assert s["preferences"]["venv"] is False


def test_global_settings_put_invalid_audience_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "junior",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_invalid_max_turns_returns_422(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "-1",
        },
    )
    assert r.status_code == 422


# ---- Notifications tab round-trip ------------------------------------------


def test_global_settings_put_notifications_email_writes_section(
    settings_client, tmp_path
):
    """Email channel enabled + populated fields → [notifications.email] table."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_enabled": "on",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com, bob@example.com",
            "notifications_email_smtp_host": "smtp.example.com",
            "notifications_email_smtp_port": "587",
            "notifications_email_smtp_user": "bot",
            "notifications_email_smtp_password_env": "SMTP_PW",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert "email" in s["notifications"]["channels"]
    email = s["notifications"]["email"]
    assert email["from_addr"] == "bot@example.com"
    assert email["to"] == ["alice@example.com", "bob@example.com"]
    assert email["smtp_host"] == "smtp.example.com"
    assert email["smtp_port"] == 587


def test_global_settings_put_notifications_slack_writes_section(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_slack_enabled": "on",
            "notifications_slack_channel": "#urika",
            "notifications_slack_token_env": "SLACK_TOKEN",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert "slack" in s["notifications"]["channels"]
    assert s["notifications"]["slack"]["channel"] == "#urika"
    assert s["notifications"]["slack"]["token_env"] == "SLACK_TOKEN"


def test_global_settings_put_notifications_telegram_writes_section(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_telegram_enabled": "on",
            "notifications_telegram_chat_id": "12345",
            "notifications_telegram_bot_token_env": "TG_TOKEN",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert "telegram" in s["notifications"]["channels"]
    assert s["notifications"]["telegram"]["chat_id"] == "12345"
    assert s["notifications"]["telegram"]["bot_token_env"] == "TG_TOKEN"


def test_global_settings_put_notifications_disabled_no_channel(
    settings_client, tmp_path
):
    """A channel without the enabled checkbox is not written into [channels]."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            # Email fields filled in, but the enable checkbox is not on
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert "email" not in s.get("notifications", {}).get("channels", [])


# ---- Response shape --------------------------------------------------------


def test_global_settings_put_returns_html_fragment_by_default(settings_client):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
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
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["privacy_mode"] == "open"
    assert body["default_max_turns"] == 10
