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


# ---- Commit 9: tab ordering + Models tab per-mode constraints -------------


def test_project_settings_tab_order_basics_data_privacy_models_notifications(
    client_with_projects,
):
    """Tabs render in order: Basics → Data → Privacy → Models → Notifications."""
    body = client_with_projects.get("/projects/alpha/settings").text
    # Find each tab button's position; assert ascending positions.
    positions = []
    for label in ("Basics", "Data", "Privacy", "Models", "Notifications"):
        marker = f">{label}</button>"
        idx = body.find(marker)
        assert idx != -1, f"missing tab button: {label}"
        positions.append(idx)
    assert positions == sorted(positions), (
        f"tab order is wrong: positions {positions} for "
        f"Basics/Data/Privacy/Models/Notifications"
    )


def _set_project_privacy(tmp_path, mode: str) -> None:
    """Helper: write a [privacy].mode to alpha/urika.toml.

    Also pre-seeds a global ``private`` endpoint so the per-agent
    endpoint dropdowns have something to render — multi-endpoint
    semantics: the dropdown lists every defined endpoint, so an empty
    globals settings file would render an empty dropdown.
    """
    proj = tmp_path / "alpha" / "urika.toml"
    proj.write_text(
        proj.read_text() + f'\n[privacy]\nmode = "{mode}"\n'
    )
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n',
        encoding="utf-8",
    )


def test_project_settings_models_open_mode_endpoint_dropdown_full(
    client_with_projects, tmp_path
):
    """In open mode every agent's endpoint dropdown offers open + private."""
    _set_project_privacy(tmp_path, "open")
    body = client_with_projects.get("/projects/alpha/settings").text
    # Each per-agent endpoint select must contain both 'open' and 'private'.
    # Be precise: check we have an option with value="open" inside the
    # endpoint[task_agent] select.
    assert '<option value="open"' in body
    assert '<option value="private"' in body


def test_project_settings_models_private_mode_hides_open(
    client_with_projects, tmp_path
):
    """Private mode hides the 'open' endpoint option for every agent."""
    _set_project_privacy(tmp_path, "private")
    body = client_with_projects.get("/projects/alpha/settings").text
    # 'open' must not appear as an endpoint <option value=...>.
    # The 'inherit' sentinel is still allowed as a no-override marker.
    # The 'private' option remains.
    assert '<option value="open"' not in body
    assert '<option value="private"' in body


def test_project_settings_models_hybrid_data_agent_forced_private(
    client_with_projects, tmp_path
):
    """In hybrid mode data_agent + tool_builder are marked force_private.

    The template renders a 'private only (hybrid)' note next to the
    forced-private agent rows so the user sees why the dropdown is
    restricted.
    """
    _set_project_privacy(tmp_path, "hybrid")
    body = client_with_projects.get("/projects/alpha/settings").text
    # The data_agent + tool_builder rows must show the "private only" hint.
    # Two rows → at least two occurrences of the hint.
    assert body.count("private only (hybrid)") >= 2


def test_project_settings_runtime_model_is_select_in_open_mode(
    tmp_path, monkeypatch
):
    """Project Models tab's project-wide model override is a <select>
    of known Claude models when the project's mode is ``open``."""
    import json
    import re

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
        '\n'
        '[privacy]\n'
        'mode = "open"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    body = client.get("/projects/alpha/settings").text
    m = re.search(
        r'<select[^>]*name="runtime_model"[^>]*>(.*?)</select>',
        body,
        flags=re.DOTALL,
    )
    assert m is not None, "runtime_model should be a <select> in open mode"
    block = m.group(1)
    assert 'value="claude-opus-4-7"' in block
    assert 'value="claude-sonnet-4-5"' in block
    assert 'value="claude-haiku-4-5"' in block


def test_project_settings_runtime_model_is_text_in_private_mode(
    tmp_path, monkeypatch
):
    """In private mode the project-wide model override stays free-text —
    local model names don't fit a fixed dropdown."""
    import json
    import re

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
        '\n'
        '[privacy]\n'
        'mode = "private"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    body = client.get("/projects/alpha/settings").text
    # No <select name="runtime_model"> in private mode.
    assert re.search(r'<select[^>]*name="runtime_model"', body) is None
    # A text input exists.
    assert re.search(
        r'<input[^>]*type="text"[^>]*name="runtime_model"', body
    )


def test_project_settings_per_agent_model_stays_free_text(
    tmp_path, monkeypatch
):
    """Per-agent model fields stay free-text in every project mode —
    the user might point at a custom-named cloud model OR a local
    model that isn't in any fixed list."""
    import json
    import re

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
        '\n'
        '[privacy]\n'
        'mode = "open"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))
    body = client.get("/projects/alpha/settings").text
    # task_agent's model input is a text input, not a <select>.
    m = re.search(
        r'<input[^>]*type="text"[^>]*name="model\[task_agent\]"',
        body,
    )
    assert m is not None


def test_project_settings_models_endpoint_dropdown_lists_named_endpoints(
    tmp_path, monkeypatch
):
    """Project Models tab's per-agent endpoint dropdown lists every
    named endpoint defined on globals' Privacy tab — not just
    ``private``.  Mode constraints still apply.
    """
    import json

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
        '\n'
        '[privacy]\n'
        'mode = "open"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    (home / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
        '\n'
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n'
    )
    client = TestClient(create_app(project_root=tmp_path))
    body = client.get("/projects/alpha/settings").text
    # Open mode: every named endpoint + the implicit ``open`` shows up.
    assert '<option value="open"' in body
    assert '<option value="private"' in body
    assert '<option value="ollama"' in body


def test_project_settings_put_per_agent_endpoint_accepts_named_endpoint(
    tmp_path, monkeypatch
):
    """Setting per-agent endpoint to a name defined in globals writes
    it to the project's [runtime.models.<agent>] block."""
    import json

    import tomllib

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    (home / "settings.toml").write_text(
        '[privacy.endpoints.ollama]\n'
        'base_url = "http://localhost:11435"\n'
        'api_key_env = ""\n'
    )
    client = TestClient(create_app(project_root=tmp_path))
    r = client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "q",
            "description": "",
            "mode": "exploratory",
            "audience": "expert",
            "model[task_agent]": "llama3:8b",
            "endpoint[task_agent]": "ollama",
        },
    )
    assert r.status_code == 200
    toml = tomllib.loads((proj / "urika.toml").read_text())
    assert toml["runtime"]["models"]["task_agent"]["endpoint"] == "ollama"


def test_project_settings_put_per_agent_endpoint_rejects_undefined_name(
    tmp_path, monkeypatch
):
    """Per-agent endpoint pointing at an undefined name returns 422."""
    import json

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    # Globals define only ``private`` — ``does_not_exist`` is unknown.
    (home / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n'
    )
    client = TestClient(create_app(project_root=tmp_path))
    r = client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "q",
            "description": "",
            "mode": "exploratory",
            "audience": "expert",
            "model[task_agent]": "llama3:8b",
            "endpoint[task_agent]": "does_not_exist",
        },
    )
    assert r.status_code == 422


def test_project_settings_models_placeholder_from_global_per_mode(
    tmp_path, monkeypatch
):
    """Project Models grid surfaces global per-mode default as placeholder.

    Sets the global ``[runtime.modes.private].models.task_agent.model``
    and asserts the project's task_agent input renders that value as
    its placeholder. Mirrors how live-inheritance from globals is
    visible to the user.
    """
    import json

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    # Tmp project + URIKA_HOME with global per-mode default set.
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\n'
        'name = "alpha"\n'
        'question = "q"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        '\n'
        '[preferences]\n'
        'audience = "expert"\n'
        '\n'
        '[privacy]\n'
        'mode = "private"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({
        "alpha": str(proj),
    }))
    (home / "settings.toml").write_text(
        '[runtime.modes.private]\n'
        'model = "qwen3:14b"\n'
        '\n'
        '[runtime.modes.private.models.task_agent]\n'
        'model = "qwen3:32b"\n'
        'endpoint = "private"\n'
    )
    client = TestClient(create_app(project_root=tmp_path))
    body = client.get("/projects/alpha/settings").text
    # Per-agent placeholder for task_agent comes from the global
    # [runtime.modes.private.models.task_agent].model.
    assert 'name="model[task_agent]"' in body
    assert 'placeholder="qwen3:32b"' in body
    # Project-wide placeholder pulls the per-mode default model.
    assert 'name="runtime_model"' in body
    assert 'placeholder="qwen3:14b"' in body
