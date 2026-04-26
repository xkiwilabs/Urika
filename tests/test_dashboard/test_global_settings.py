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


def test_global_settings_privacy_tab_multi_endpoint_editor(settings_client, tmp_path):
    """Privacy tab is a multi-endpoint editor.  Each row defines a
    named endpoint under ``[privacy.endpoints.<name>]``.  Pre-existing
    endpoints render as Alpine-bound rows so the user can edit / remove
    them; an "+ Add endpoint" button appends a fresh empty row.
    """
    # Pre-seed one endpoint so the page renders with a row pre-filled.
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # The Alpine x-data carries the named endpoints list.
    assert "endpoints:" in body
    # Pre-seeded endpoint surfaces in the Alpine state.
    assert "private" in body
    assert "http://localhost:11434" in body
    # The Privacy tab now serializes the endpoints array to a single
    # JSON field at submit time (avoids Alpine :name= timing edge cases
    # that prevented the form from including dynamically-added rows).
    # Each row has x-model bindings on its inputs.
    assert 'x-model="ep.name"' in body
    assert 'x-model="ep.base_url"' in body
    assert 'x-model="ep.api_key_env"' in body
    assert 'x-model="ep.default_model"' in body
    # The configRequest hook injects endpoints_json into the request.
    assert "endpoints_json" in body
    # The "+ Add endpoint" button is present.
    assert "+ Add endpoint" in body
    # Mode picker MUST NOT be on the global Privacy tab any more.
    assert 'name="privacy_mode"' not in body
    # Per-mode model fields are gone from this tab.
    assert 'name="privacy_open_model"' not in body
    assert 'name="privacy_private_model"' not in body
    assert 'name="privacy_hybrid_cloud_model"' not in body
    assert 'name="privacy_hybrid_private_url"' not in body
    assert 'name="privacy_hybrid_private_key_env"' not in body
    assert 'name="privacy_hybrid_private_model"' not in body
    # Legacy single-endpoint form fields are gone.
    assert 'name="privacy_private_url"' not in body
    assert 'name="privacy_private_key_env"' not in body


def test_global_settings_models_tab_has_per_mode_grids(settings_client, tmp_path):
    """Models tab renders three grids (open / private / hybrid).

    Per the per-mode shape redesign:
      * Open mode rows submit ``[model]`` (cloud-models <select>) plus
        a hidden ``[endpoint]=open``.  No endpoint <select>.
      * Private mode rows submit ``[endpoint]`` (a <select> of named
        private endpoints) plus a hidden ``[model]`` derived (via
        Alpine) from the chosen endpoint's default_model.
      * Hybrid mode rows submit BOTH ``[endpoint]`` and ``[model]``
        (the model widget swaps per chosen endpoint).
    """
    # Pre-seed a private endpoint with a default_model so the private
    # grid actually renders the per-agent rows (it shows an empty-state
    # otherwise).
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    # Sub-tabs (UI-only; not posted to the server).
    assert ">Open</button>" in body
    assert ">Private</button>" in body
    assert ">Hybrid</button>" in body
    # One default-model field per mode.
    for mode_name in ("open", "private", "hybrid"):
        assert f'name="runtime_modes_{mode_name}_model"' in body
    agents = (
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
    )
    # Open mode: each row sends a model field + hidden endpoint.
    for agent in agents:
        assert f'name="runtime_modes_open_models[{agent}][model]"' in body
        assert f'name="runtime_modes_open_models[{agent}][endpoint]"' in body
    # Private mode: each row sends an endpoint + (Alpine-derived) model.
    for agent in agents:
        assert f'name="runtime_modes_private_models[{agent}][model]"' in body
        assert (
            f'name="runtime_modes_private_models[{agent}][endpoint]"' in body
        )
    # Hybrid mode: each row sends both endpoint and model.
    for agent in agents:
        assert f'name="runtime_modes_hybrid_models[{agent}][model]"' in body
        assert f'name="runtime_modes_hybrid_models[{agent}][endpoint]"' in body


def _seed_private_endpoint(tmp_path, *, with_default_model: bool = True):
    """Pre-seed ~/.urika/settings.toml with a single ``private`` endpoint
    so the per-agent endpoint dropdowns have a value to render.

    ``with_default_model`` controls whether the endpoint also gets a
    ``default_model`` — required for the private-mode grid to render
    its per-agent rows (the grid shows an empty-state otherwise).
    """
    body = (
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
    )
    if with_default_model:
        body += 'default_model = "qwen3:14b"\n'
    (tmp_path / "home" / "settings.toml").write_text(body, encoding="utf-8")


def test_global_settings_models_tab_hybrid_forces_private_for_data_and_tool_builder(
    settings_client, tmp_path
):
    """In the hybrid grid, data_agent + tool_builder rows offer ONLY the
    'private' endpoint option (the cloud option is hidden)."""
    import re

    _seed_private_endpoint(tmp_path)
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
    settings_client, tmp_path
):
    """In the private grid, every agent's endpoint dropdown offers ONLY
    private endpoints — the cloud option never appears."""
    import re

    _seed_private_endpoint(tmp_path)
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


def test_global_settings_models_open_default_model_is_select(settings_client):
    """Open mode's per-mode default model field is a <select> dropdown
    of known Claude models — not a free-text input."""
    import re

    body = settings_client.get("/settings").text
    # The <select> wraps known cloud model options.
    m = re.search(
        r'<select[^>]*name="runtime_modes_open_model"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, "open-mode default model is not a <select>"
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block
    assert 'value="claude-sonnet-4-5"' in block
    assert 'value="claude-haiku-4-5"' in block


def test_global_settings_models_hybrid_default_model_is_select(settings_client):
    """Hybrid mode's per-mode default model field is also a <select>
    of known Claude models (the cloud-side default)."""
    import re

    body = settings_client.get("/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_modes_hybrid_model"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, "hybrid-mode default model is not a <select>"
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block


def test_global_settings_models_open_mode_per_agent_model_is_cloud_select(
    settings_client,
):
    """Open mode rows are all cloud (no endpoint column).  Each row's
    model field is a <select> of known cloud Claude models — the user
    is always picking a Claude variant in open mode."""
    import re

    body = settings_client.get("/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_modes_open_models\[task_agent\]\[model\]"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, (
        "open-mode per-agent model field should be a <select> of cloud models"
    )
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block
    assert 'value="claude-sonnet-4-5"' in block
    assert 'value="claude-haiku-4-5"' in block


def test_global_settings_models_open_mode_drops_endpoint_dropdown(
    settings_client,
):
    """In open mode every agent uses the cloud endpoint by definition,
    so the endpoint column is gone and a hidden ``[endpoint]=open``
    travels with each row instead."""
    import re

    body = settings_client.get("/settings").text
    # Hidden input present, value "open".
    m = re.search(
        r'<input[^>]*type="hidden"[^>]*name="runtime_modes_open_models\[task_agent\]\[endpoint\]"[^>]*value="open"',
        body,
    )
    assert m is not None
    # No <select> for the open-mode endpoint — the column has been
    # dropped on the open grid.
    m_select = re.search(
        r'<select[^>]*name="runtime_modes_open_models\[task_agent\]\[endpoint\]"',
        body,
    )
    assert m_select is None


def test_global_settings_models_private_mode_drops_endpoint_column(
    settings_client, tmp_path
):
    """Private mode also drops the endpoint column.  The model select
    IS the endpoint chooser — its option values are endpoint names and
    its labels are ``<default_model> (<endpoint_name>)``."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_modes_private_models\[task_agent\]\[endpoint\]"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(1)
    # Option label is "<default_model> (<endpoint_name>)".
    assert "qwen3:14b (private)" in block
    # The matching hidden model input is bound via Alpine to the
    # chosen endpoint's default_model.
    assert (
        'name="runtime_modes_private_models[task_agent][model]"' in body
    )


def test_global_settings_models_private_mode_empty_state_when_no_endpoints(
    settings_client,
):
    """When no private endpoints have a default_model defined, the
    private grid renders an empty state pointing at the Privacy tab."""
    body = settings_client.get("/settings").text
    # Empty-state phrase + a "Configure endpoints" link to the Privacy tab.
    assert "No private endpoints" in body
    assert "Configure endpoints" in body


def test_global_settings_models_hybrid_row_has_alpine_state(
    settings_client, tmp_path
):
    """Hybrid rows carry an Alpine ``x-data`` block whose ``ep`` field
    drives the conditional model widget (cloud-models <select> vs
    auto-populated read-only display)."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    # Alpine state declared per row — task_agent is non-forced, so it
    # will at minimum carry the ``ep`` field initialised from the saved
    # value (or "open" by default).
    m = re.search(
        r'<tr[^>]*x-data=\'{ ep:[^\']*\'[^>]*>\s*<td><code>task_agent</code></td>',
        body,
    )
    assert m is not None
    # The hybrid row's model widget pair: a cloud-models <select> AND
    # a hidden input — Alpine ``:disabled`` keeps only the active one
    # in the form submission.
    assert (
        'name="runtime_modes_hybrid_models[task_agent][model]"' in body
    )


def test_global_settings_models_private_default_model_is_text(settings_client):
    """Private mode's per-mode default model field stays a free-text
    input — local-server model names vary too much for a fixed list."""
    import re

    body = settings_client.get("/settings").text
    # No <select> with this name should exist.
    m_select = re.search(
        r'<select[^>]*name="runtime_modes_private_model"',
        body,
    )
    assert m_select is None
    # A text input does exist.
    m_input = re.search(
        r'<input[^>]*type="text"[^>]*name="runtime_modes_private_model"',
        body,
    )
    assert m_input is not None


def test_global_settings_models_tab_hybrid_mode_offers_both_endpoints(
    settings_client, tmp_path
):
    """Hybrid mode keeps the endpoint dropdown — non-forced agents
    can pick either ``open`` or any defined private endpoint."""
    import re

    _seed_private_endpoint(tmp_path)
    body = settings_client.get("/settings").text
    m = re.search(
        r'name="runtime_modes_hybrid_models\[task_agent\]\[endpoint\]".*?</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    assert 'value="open"' in block
    assert 'value="private"' in block


def test_global_settings_models_tab_hybrid_mode_lists_all_named_endpoints(
    settings_client, tmp_path
):
    """When multiple named endpoints are defined, the hybrid-mode
    per-agent dropdown lists every one of them (alongside ``open``
    for non-forced agents)."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n'
        'default_model = "llama3:8b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    m = re.search(
        r'name="runtime_modes_hybrid_models\[task_agent\]\[endpoint\]".*?</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    assert 'value="open"' in block
    assert 'value="private"' in block
    assert 'value="ollama"' in block


def test_global_settings_models_tab_private_mode_lists_all_named_endpoints(
    settings_client, tmp_path
):
    """Private mode's per-agent model <select> lists every defined
    private endpoint (the model field IS the endpoint chooser).  No
    ``open`` option appears."""
    import re

    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        'default_model = "qwen3:14b"\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n'
        'default_model = "llama3:8b"\n',
        encoding="utf-8",
    )
    body = settings_client.get("/settings").text
    m = re.search(
        r'name="runtime_modes_private_models\[task_agent\]\[endpoint\]".*?</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None
    block = m.group(0)
    assert 'value="open"' not in block
    assert 'value="private"' in block
    assert 'value="ollama"' in block
    # Labels carry the default_model in parens.
    assert "qwen3:14b (private)" in block
    assert "llama3:8b (ollama)" in block


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


def test_global_settings_put_single_endpoint_writes_section(
    settings_client, tmp_path
):
    """Submitting a single named endpoint via the multi-endpoint form
    writes ``[privacy.endpoints.<name>]``. No mode is written to globals."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
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


def test_global_settings_put_multiple_endpoints_writes_each(
    settings_client, tmp_path
):
    """Submitting two endpoints (private + ollama) writes both blocks
    under ``[privacy.endpoints]``."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "qwen3:14b",
            "endpoints[1][name]": "ollama",
            "endpoints[1][base_url]": "http://localhost:11435",
            "endpoints[1][api_key_env]": "",
            "endpoints[1][default_model]": "llama3:8b",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    eps = s["privacy"]["endpoints"]
    assert eps["private"]["base_url"] == "http://localhost:11434"
    assert eps["private"]["default_model"] == "qwen3:14b"
    assert eps["ollama"]["base_url"] == "http://localhost:11435"
    assert eps["ollama"]["default_model"] == "llama3:8b"


def test_global_settings_put_omitting_endpoint_deletes_it(
    settings_client, tmp_path
):
    """An endpoint present in the previous TOML but absent from the
    new submission is REMOVED — diff-apply semantics so the user can
    delete an endpoint by simply unmounting its row."""
    # Pre-seed two endpoints.
    (tmp_path / "home" / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n',
        encoding="utf-8",
    )
    # Submit only one of the two — the other should be deleted.
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    eps = s["privacy"]["endpoints"]
    assert "private" in eps
    assert "ollama" not in eps


def test_global_settings_put_reserved_endpoint_name_rejected(settings_client):
    """The name ``open`` is reserved (it's the implicit cloud endpoint
    name) and submitting it returns 422."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "open",
            "endpoints[0][base_url]": "http://example.com",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_invalid_endpoint_name_rejected(settings_client):
    """An endpoint name with spaces (or any character outside
    ``[a-z0-9_-]``) returns 422."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "Has Spaces",
            "endpoints[0][base_url]": "http://example.com",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
        },
    )
    assert r.status_code == 422


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
    """[runtime.models.<agent>] is populated from model[<agent>] form fields.

    Requires the named endpoint ``private`` to actually exist — multi-
    endpoint validation rejects per-agent endpoint values that don't
    match a defined endpoint or the implicit ``open``.
    """
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
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
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
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
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
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


def test_global_settings_put_per_agent_endpoint_accepts_named_endpoint(
    settings_client, tmp_path
):
    """A per-agent endpoint value matching a defined named endpoint
    (anything beyond ``open`` / ``private``) round-trips to the TOML."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "endpoints[1][name]": "ollama",
            "endpoints[1][base_url]": "http://localhost:11435",
            "endpoints[1][api_key_env]": "",
            "endpoints[1][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_open_models[task_agent][model]": "llama3:8b",
            "runtime_modes_open_models[task_agent][endpoint]": "ollama",
        },
    )
    assert r.status_code == 200
    s = tomllib.loads((tmp_path / "home" / "settings.toml").read_text())
    assert (
        s["runtime"]["modes"]["open"]["models"]["task_agent"]["endpoint"]
        == "ollama"
    )


def test_global_settings_put_per_agent_endpoint_rejects_undefined_name(
    settings_client, tmp_path
):
    """A per-agent endpoint pointing at an undefined endpoint name
    returns 422."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
            "default_audience": "expert",
            "default_max_turns": "10",
            "runtime_modes_open_model": "claude-opus-4-7",
            "runtime_modes_open_models[task_agent][model]": "llama3:8b",
            # No endpoint named ``does_not_exist`` is defined → 422.
            "runtime_modes_open_models[task_agent][endpoint]": "does_not_exist",
        },
    )
    assert r.status_code == 422


def test_global_settings_put_private_mode_coerces_open_endpoint_to_private(
    settings_client, tmp_path
):
    """Private mode hides the cloud option in the UI; the API enforces
    the same rule (any endpoint=open submission is coerced)."""
    r = settings_client.put(
        "/api/settings",
        data={
            "endpoints[0][name]": "private",
            "endpoints[0][base_url]": "http://localhost:11434",
            "endpoints[0][api_key_env]": "",
            "endpoints[0][default_model]": "",
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
