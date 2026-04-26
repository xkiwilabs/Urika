"""Tests for project settings (read) page."""

from __future__ import annotations


def test_project_settings_returns_200_and_renders_form(client_with_projects):
    r = client_with_projects.get("/projects/alpha/settings")
    assert r.status_code == 200
    body = r.text
    # Form fields with the right name attributes
    assert 'name="question"' in body
    assert 'name="description"' in body
    assert 'name="mode"' in body
    assert 'name="audience"' in body
    # HTMX directive on the form
    assert 'hx-put="/api/projects/alpha/settings"' in body
    # Current mode is selected
    assert "exploratory" in body


def test_project_settings_404_unknown_project(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/settings")
    assert r.status_code == 404


def test_project_settings_shows_all_valid_modes(client_with_projects):
    r = client_with_projects.get("/projects/alpha/settings")
    body = r.text
    for mode in ("exploratory", "confirmatory", "pipeline"):
        assert mode in body


# ---- 5-tab layout -------------------------------------------------------


def test_project_settings_has_five_tab_buttons(client_with_projects):
    """Page renders with 5 tabs: Basics / Data / Models / Privacy / Notifications."""
    r = client_with_projects.get("/projects/alpha/settings")
    body = r.text
    for label in ("Basics", "Data", "Models", "Privacy", "Notifications"):
        assert f">{label}</button>" in body, f"missing tab button: {label}"


def test_project_settings_data_tab_has_data_paths_and_criteria(client_with_projects):
    """Data tab exposes textareas for data_paths and success_criteria."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'name="data_paths"' in body
    assert 'name="success_criteria"' in body


def test_project_settings_models_tab_has_per_agent_rows(client_with_projects):
    """Models tab renders one row per known agent with model + endpoint inputs."""
    body = client_with_projects.get("/projects/alpha/settings").text
    # Project-wide override
    assert 'name="runtime_model"' in body
    # Hardcoded KNOWN_AGENTS list
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


def test_project_settings_privacy_tab_renders_three_radio_options(
    client_with_projects,
):
    """Privacy tab: 3-option radio (open / private / hybrid). The
    legacy 'inherit' option is gone — there is no system-wide default
    mode any more, so each project owns its mode."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'name="project_privacy_mode"' in body
    for value in ("open", "private", "hybrid"):
        assert f'value="{value}"' in body
    # 'inherit' must NOT be a project_privacy_mode radio option any more.
    # (The Models tab's endpoint dropdown still uses 'inherit' as a
    # per-agent "no override" sentinel — that's unrelated.)
    assert 'name="project_privacy_mode" value="inherit"' not in body


def test_project_settings_privacy_tab_has_per_mode_fields(client_with_projects):
    """Privacy tab renders per-mode fields for open / private / hybrid."""
    body = client_with_projects.get("/projects/alpha/settings").text
    # Open block
    assert 'name="project_privacy_open_model"' in body
    # Private block
    assert 'name="project_privacy_private_url"' in body
    assert 'name="project_privacy_private_key_env"' in body
    assert 'name="project_privacy_private_model"' in body
    # Hybrid block
    assert 'name="project_privacy_hybrid_cloud_model"' in body
    assert 'name="project_privacy_hybrid_private_url"' in body
    assert 'name="project_privacy_hybrid_private_key_env"' in body
    assert 'name="project_privacy_hybrid_private_model"' in body


def test_project_settings_privacy_tab_no_inherit_label(
    client_with_projects,
):
    """The 'Inherit from global' label is gone — modes are project-owned."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert "Inherit from global" not in body


def test_project_settings_notifications_tab_has_per_channel_enabled_checkbox(
    client_with_projects,
):
    """Notifications tab exposes a single enabled checkbox per channel
    plus the per-channel override fields. The legacy 3-state radios
    (``project_notif_<ch>_state``) and the ``_disabled`` sentinel are
    gone — global ``auto_enable`` covers the inherit case at creation
    time."""
    body = client_with_projects.get("/projects/alpha/settings").text
    # Per-channel enabled checkboxes (NEW 2-state model)
    for ch in ("email", "slack", "telegram"):
        assert f'name="project_notif_{ch}_enabled"' in body
    # Email-specific extra_to
    assert 'name="project_notif_email_extra_to"' in body
    # Telegram-specific override_chat_id
    assert 'name="project_notif_telegram_override_chat_id"' in body
    # Legacy state radios are gone
    for ch in ("email", "slack", "telegram"):
        assert f'name="project_notif_{ch}_state"' not in body


def test_project_settings_uses_tabs_macro(client_with_projects):
    """The page uses the tabs macro from _macros.html (Alpine x-data scope)."""
    body = client_with_projects.get("/projects/alpha/settings").text
    assert 'x-data="{ active:' in body
    assert "tab-button" in body
