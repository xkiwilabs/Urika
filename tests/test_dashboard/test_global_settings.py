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


def test_global_settings_privacy_tab_endpoint_only(settings_client):
    """Privacy tab now exposes just the private endpoint connection
    details. The default-mode picker and per-mode model fields are gone
    — mode lives at project creation, per-mode model defaults live on
    the Models tab."""
    body = settings_client.get("/settings").text
    # Mode picker MUST NOT be on the global Privacy tab any more.
    assert 'name="privacy_mode"' not in body
    # Private endpoint URL + key env are the only fields.
    assert 'name="privacy_private_url"' in body
    assert 'name="privacy_private_key_env"' in body
    # Per-mode model fields are gone from this tab.
    assert 'name="privacy_open_model"' not in body
    assert 'name="privacy_private_model"' not in body
    assert 'name="privacy_hybrid_cloud_model"' not in body
    assert 'name="privacy_hybrid_private_url"' not in body
    assert 'name="privacy_hybrid_private_key_env"' not in body
    assert 'name="privacy_hybrid_private_model"' not in body


def test_global_settings_models_tab_has_per_mode_grids(settings_client):
    """Models tab renders three grids (open / private / hybrid), each
    with a default-model field + per-agent rows.  Form names follow the
    new bracketed scheme: ``runtime_modes_<mode>_model`` and
    ``runtime_modes_<mode>_models[<agent>][model|endpoint]``."""
    body = settings_client.get("/settings").text
    # Mode picker (UI-only; not posted to the server).
    assert 'id="models_mode_picker"' in body
    # One default-model field per mode.
    for mode_name in ("open", "private", "hybrid"):
        assert f'name="runtime_modes_{mode_name}_model"' in body
    # Per-agent rows under each mode use the bracketed naming convention.
    for mode_name in ("open", "private", "hybrid"):
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
            assert (
                f'name="runtime_modes_{mode_name}_models[{agent}][model]"'
                in body
            )
            assert (
                f'name="runtime_modes_{mode_name}_models[{agent}][endpoint]"'
                in body
            )


def test_global_settings_models_tab_hybrid_forces_private_for_data_and_tool_builder(
    settings_client,
):
    """In the hybrid grid, data_agent + tool_builder rows offer ONLY the
    'private' endpoint option (the cloud option is hidden)."""
    import re

    body = settings_client.get("/settings").text
    # data_agent's hybrid endpoint <select> must contain 'private' but NOT
    # an 'open' option.
    for forced_agent in ("data_agent", "tool_builder"):
        m = re.search(
            r'name="runtime_modes_hybrid_models\['
            + forced_agent
            + r'\]\[endpoint\]".*?</select>',
            body,
            flags=re.DOTALL,
        )
        assert m is not None, f"missing endpoint select for {forced_agent}"
        block = m.group(0)
        assert 'value="private"' in block
        assert 'value="open"' not in block


def test_global_settings_models_tab_private_mode_hides_open_for_all_agents(
    settings_client,
):
    """In the private grid, every agent's endpoint dropdown offers ONLY
    'private' — the cloud option is hidden."""
    import re

    body = settings_client.get("/settings").text
    for agent in ("task_agent", "evaluator", "advisor_agent"):
        m = re.search(
            r'name="runtime_modes_private_models\['
            + agent
            + r'\]\[endpoint\]".*?</select>',
            body,
            flags=re.DOTALL,
        )
        assert m is not None
        block = m.group(0)
        assert 'value="private"' in block
        assert 'value="open"' not in block


def test_global_settings_models_tab_open_mode_offers_both_endpoints(
    settings_client,
):
    """Open mode's per-agent endpoint dropdown offers both 'open' and
    'private'."""
    import re

    body = settings_client.get("/settings").text
    m = re.search(
        r'name="runtime_modes_open_models\[task_agent\]\[endpoint\]".*?</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    assert 'value="open"' in block
    assert 'value="private"' in block


def test_global_settings_preferences_tab_has_expected_fields(settings_client):
    """Preferences tab exposes audience, max_turns, web_search, venv."""
    body = settings_client.get("/settings").text
    assert 'name="default_audience"' in body
    assert 'name="default_max_turns"' in body
    assert 'name="web_search"' in body
    assert 'name="venv"' in body


def test_global_settings_venv_checkbox_unset_means_unchecked(settings_client):
    """venv default is OFF — when settings.toml has no venv preference,
    the checkbox renders unchecked. (The default is to use the global
    urika venv, not per-project.)"""
    import re

    body = settings_client.get("/settings").text
    m = re.search(r'<input[^>]*name="venv"[^>]*>', body)
    assert m is not None, "venv checkbox not found"
    assert "checked" not in m.group(0)


def test_global_settings_notifications_tab_has_channels(settings_client):
    """Notifications tab exposes per-channel CONNECTION fields plus
    a per-channel ``auto_enable`` checkbox that decides whether new
    projects start with the channel turned on. Per-project run-time
    enablement still lives on the project Notifications tab.
    """
    body = settings_client.get("/settings").text
    # Email — connection details
    assert 'name="notifications_email_from"' in body
    assert 'name="notifications_email_to"' in body
    assert 'name="notifications_email_smtp_host"' in body
    assert 'name="notifications_email_smtp_port"' in body
    # Slack — connection details
    assert 'name="notifications_slack_channel"' in body
    assert 'name="notifications_slack_token_env"' in body
    # Telegram — connection details
    assert 'name="notifications_telegram_chat_id"' in body
    assert 'name="notifications_telegram_bot_token_env"' in body
    # Per-channel auto_enable checkboxes (NEW)
    assert 'name="notifications_email_auto_enable"' in body
    assert 'name="notifications_slack_auto_enable"' in body
    assert 'name="notifications_telegram_auto_enable"' in body
    # The legacy per-channel "enabled" checkboxes are still NOT on the
    # global form — channel enablement is per-project.
    assert 'name="notifications_email_enabled"' not in body
    assert 'name="notifications_slack_enabled"' not in body
    assert 'name="notifications_telegram_enabled"' not in body


def test_global_settings_auto_enable_checkbox_reflects_saved_value(
    settings_client, tmp_path
):
    """When ``[notifications.email].auto_enable`` is true in settings.toml,
    the checkbox renders pre-checked."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        "[notifications.email]\n"
        'from_addr = "x@y.com"\n'
        "auto_enable = true\n",
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    m = re.search(
        r'<input[^>]*name="notifications_email_auto_enable"[^>]*>', body
    )
    assert m is not None, "email auto_enable checkbox not found"
    assert "checked" in m.group(0)

    # Slack/telegram unset → unchecked.
    m_slack = re.search(
        r'<input[^>]*name="notifications_slack_auto_enable"[^>]*>', body
    )
    assert m_slack is not None
    assert "checked" not in m_slack.group(0)


# ---- Privacy tab round-trips -----------------------------------------------


def test_global_settings_put_private_endpoint_writes_section(
    settings_client, tmp_path
):
    """Submitting the private endpoint URL + key env writes
    [privacy.endpoints.private]. No mode is written to globals."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_private_url": "http://localhost:11434",
            "privacy_private_key_env": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["privacy"]["endpoints"]["private"]["base_url"]
        == "http://localhost:11434"
    )
    # No system-wide default mode is persisted any more.
    assert "mode" not in s.get("privacy", {})


def test_global_settings_put_drops_legacy_privacy_mode(settings_client, tmp_path):
    """Saving never writes [privacy].mode — and an existing legacy
    value is dropped on the next save."""
    # Pre-seed with a legacy [privacy].mode that older code wrote
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy]\nmode = "private"\n', encoding="utf-8"
    )
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert "mode" not in s.get("privacy", {})


def test_global_settings_put_ignores_unknown_privacy_mode_field(settings_client):
    """Old clients posting a privacy_mode= value get ignored, not 422.
    The field is no longer part of the global form."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "bogus",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200


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


# ---- Per-mode model defaults round-trip ------------------------------------


def test_global_settings_put_per_mode_default_model_writes_runtime_modes(
    settings_client, tmp_path
):
    """``runtime_modes_<mode>_model`` populates
    ``[runtime.modes.<mode>].model``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_private_model": "qwen3:14b",
            "runtime_modes_hybrid_model": "claude-sonnet-4-5",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["runtime"]["modes"]["open"]["model"] == "claude-opus-4-7"
    assert s["runtime"]["modes"]["private"]["model"] == "qwen3:14b"
    assert s["runtime"]["modes"]["hybrid"]["model"] == "claude-sonnet-4-5"


def test_global_settings_put_per_mode_per_agent_writes_models_subtable(
    settings_client, tmp_path
):
    """``runtime_modes_<mode>_models[<agent>][model|endpoint]`` populates
    ``[runtime.modes.<mode>.models.<agent>]``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_open_models[task_agent][model]": "claude-haiku-4-5",
            "runtime_modes_open_models[task_agent][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["open"]["models"]["task_agent"]["model"]
        == "claude-haiku-4-5"
    )
    assert (
        s["runtime"]["modes"]["open"]["models"]["task_agent"]["endpoint"]
        == "open"
    )


def test_global_settings_put_hybrid_forces_data_agent_private(
    settings_client, tmp_path
):
    """A hybrid-mode submission that tries endpoint=open for data_agent
    is silently coerced to endpoint=private — server-side enforcement of
    the forced-private rule."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_hybrid_model": "claude-sonnet-4-5",
            "runtime_modes_hybrid_models[data_agent][model]": "qwen3:14b",
            # UI shouldn't allow this, but defensive enforcement matters.
            "runtime_modes_hybrid_models[data_agent][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["hybrid"]["models"]["data_agent"]["endpoint"]
        == "private"
    )


def test_global_settings_put_hybrid_forces_tool_builder_private(
    settings_client, tmp_path
):
    """tool_builder joins data_agent in the forced-private set."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_hybrid_model": "claude-sonnet-4-5",
            "runtime_modes_hybrid_models[tool_builder][model]": "qwen3:14b",
            "runtime_modes_hybrid_models[tool_builder][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["hybrid"]["models"]["tool_builder"]["endpoint"]
        == "private"
    )


def test_global_settings_put_private_mode_coerces_open_endpoint_to_private(
    settings_client, tmp_path
):
    """Private mode hides the cloud option in the UI; the API enforces
    the same rule (any endpoint=open submission is coerced)."""
    r = settings_client.put(
        "/api/settings",
        data={
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_private_model": "qwen3:14b",
            "runtime_modes_private_models[task_agent][model]": "qwen3-coder",
            "runtime_modes_private_models[task_agent][endpoint]": "open",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["private"]["models"]["task_agent"]["endpoint"]
        == "private"
    )


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
    """Email connection details → [notifications.email] table.

    Channel enablement is per-project (handled elsewhere); the global
    form only persists connection details.
    """
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
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
            "notifications_slack_channel": "#urika",
            "notifications_slack_token_env": "SLACK_TOKEN",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
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
            "notifications_telegram_chat_id": "12345",
            "notifications_telegram_bot_token_env": "TG_TOKEN",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["telegram"]["chat_id"] == "12345"
    assert s["notifications"]["telegram"]["bot_token_env"] == "TG_TOKEN"


def test_global_settings_put_email_auto_enable_writes_flag(
    settings_client, tmp_path
):
    """``notifications_email_auto_enable=on`` round-trips to
    ``[notifications.email].auto_enable = true``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
            "notifications_email_auto_enable": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["email"]["auto_enable"] is True


def test_global_settings_put_slack_auto_enable_writes_flag(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_slack_channel": "#urika",
            "notifications_slack_auto_enable": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["slack"]["auto_enable"] is True


def test_global_settings_put_telegram_auto_enable_writes_flag(
    settings_client, tmp_path
):
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_telegram_chat_id": "12345",
            "notifications_telegram_auto_enable": "on",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["telegram"]["auto_enable"] is True


def test_global_settings_put_auto_enable_unchecked_writes_false(
    settings_client, tmp_path
):
    """Omitting ``notifications_<ch>_auto_enable`` from the form (i.e.
    unchecked checkbox) writes ``auto_enable = false``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
            # email auto_enable intentionally omitted
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert s["notifications"]["email"]["auto_enable"] is False


def test_global_settings_put_notifications_does_not_write_channels(
    settings_client, tmp_path
):
    """The global form never writes [notifications].channels — that
    list is per-project and managed elsewhere."""
    r = settings_client.put(
        "/api/settings",
        data={
            "privacy_mode": "open",
            "privacy_open_model": "claude-sonnet-4-5",
            "default_audience": "expert",
            "default_max_turns": "10",
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    # Email section is written (connection details set) but no channels list.
    assert "email" in s.get("notifications", {})
    assert "channels" not in s.get("notifications", {})


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
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # privacy_mode is no longer part of the global form / response.
    assert "privacy_mode" not in body
    assert body["default_max_turns"] == 10
