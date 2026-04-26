"""Tests for PUT /api/projects/<name>/settings."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _write_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f"[project]\n"
        f'name = "{name}"\n'
        f'question = "original q"\n'
        f'mode = "exploratory"\n'
        f'description = "orig desc"\n'
        f"\n"
        f"[preferences]\n"
        f'audience = "expert"\n'
    )
    return proj


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _write_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    # Pre-seed a global ``private`` endpoint so per-agent endpoint
    # overrides referencing ``private`` round-trip without 422.  The
    # project-settings PUT validates per-agent endpoint names against
    # the union of globals + project-local + the implicit ``open``.
    (home / "settings.toml").write_text(
        '[privacy.endpoints.private]\n'
        'base_url = "http://localhost:11434"\n'
        'api_key_env = ""\n',
        encoding="utf-8",
    )
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_settings_put_writes_to_disk(settings_client, tmp_path):
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "new q",
            "description": "new desc",
            "mode": "confirmatory",
            "audience": "novice",
        },
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["project"]["question"] == "new q"
    assert toml["project"]["description"] == "new desc"
    assert toml["project"]["mode"] == "confirmatory"
    assert toml["preferences"]["audience"] == "novice"


def test_settings_put_returns_html_fragment_by_default(settings_client):
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "x",
            "description": "y",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 200
    assert "Saved" in r.text


def test_settings_put_returns_json_when_requested(settings_client):
    r = settings_client.put(
        "/api/projects/alpha/settings",
        headers={"accept": "application/json"},
        data={
            "question": "json q",
            "description": "",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "json q"
    assert body["audience"] == "expert"


def test_settings_put_invalid_mode_returns_422(settings_client):
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "q",
            "description": "",
            "mode": "bogus",
            "audience": "expert",
        },
    )
    assert r.status_code == 422


def test_settings_put_invalid_audience_returns_422(settings_client):
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "q",
            "description": "",
            "mode": "exploratory",
            "audience": "junior",
        },
    )
    assert r.status_code == 422


def test_settings_put_404_unknown_project(settings_client):
    r = settings_client.put(
        "/api/projects/nonexistent/settings",
        data={
            "question": "q",
            "description": "",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 404


def test_settings_put_only_updates_changed_fields_records_revisions(
    settings_client, tmp_path
):
    # Change only the question; mode/audience/description stay same
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "different",
            "description": "orig desc",  # unchanged
            "mode": "exploratory",  # unchanged
            "audience": "expert",  # unchanged
        },
    )
    assert r.status_code == 200
    revisions_path = tmp_path / "alpha" / "revisions.json"
    assert revisions_path.exists()
    revisions = json.loads(revisions_path.read_text())["revisions"]
    fields_changed = [r["field"] for r in revisions]
    assert fields_changed == ["question"]


# ---- Data tab: data_paths + success_criteria --------------------------------


def test_settings_put_data_paths_writes_list(settings_client, tmp_path):
    """data_paths textarea (one per line) becomes a TOML list under [project]."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "data_paths": "data/one.csv\ndata/two.csv\n",
        },
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["project"]["data_paths"] == ["data/one.csv", "data/two.csv"]


def test_settings_put_data_paths_records_one_revision(settings_client, tmp_path):
    """Saving data_paths records exactly one revision entry."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "data_paths": "a.csv\nb.csv",
        },
    )
    revisions = json.loads((tmp_path / "alpha" / "revisions.json").read_text())[
        "revisions"
    ]
    fields = [r["field"] for r in revisions]
    assert fields == ["data_paths"]


def test_settings_put_data_paths_skips_blanks(settings_client, tmp_path):
    """Empty lines in the textarea are stripped, not written as ''."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "data_paths": "data/x.csv\n\n  \ndata/y.csv\n",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["project"]["data_paths"] == ["data/x.csv", "data/y.csv"]


def test_settings_put_success_criteria_parses_key_value(settings_client, tmp_path):
    """success_criteria textarea (key=value per line) → TOML inline table."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "success_criteria": "rmse_max=0.5\nr2_min=0.8\n",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    sc = toml["project"]["success_criteria"]
    # Values are stored as strings (we don't try to coerce numeric types)
    assert sc["rmse_max"] == "0.5"
    assert sc["r2_min"] == "0.8"


# ---- Models tab: per-agent overrides ---------------------------------------


def test_settings_put_runtime_model_writes_under_runtime(settings_client, tmp_path):
    """Project-wide [runtime].model override."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "runtime_model": "claude-sonnet-4-5",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["runtime"]["model"] == "claude-sonnet-4-5"


def test_settings_put_per_agent_model_writes_under_runtime_models(
    settings_client, tmp_path
):
    """[runtime.models.task_agent].model + endpoint overrides."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "model[task_agent]": "qwen3-coder",
            "endpoint[task_agent]": "private",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["runtime"]["models"]["task_agent"]["model"] == "qwen3-coder"
    assert toml["runtime"]["models"]["task_agent"]["endpoint"] == "private"


def test_settings_put_per_agent_skips_inherit_endpoint(settings_client, tmp_path):
    """endpoint=inherit means 'no override' — don't write it to disk."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "model[task_agent]": "qwen3-coder",
            "endpoint[task_agent]": "inherit",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    agent = toml["runtime"]["models"]["task_agent"]
    assert agent["model"] == "qwen3-coder"
    assert "endpoint" not in agent


def test_settings_put_skips_empty_per_agent_rows(settings_client, tmp_path):
    """Agent rows with empty model + inherit endpoint produce no TOML entry."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "model[task_agent]": "",
            "endpoint[task_agent]": "inherit",
            "model[evaluator]": "claude-haiku",
            "endpoint[evaluator]": "open",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    models = toml.get("runtime", {}).get("models", {})
    assert "task_agent" not in models
    assert models["evaluator"]["model"] == "claude-haiku"
    assert models["evaluator"]["endpoint"] == "open"


# ---- Notifications tab ------------------------------------------------------


def test_settings_put_notifications_channels_writes_section(settings_client, tmp_path):
    """[notifications].channels list is written from per-channel enabled checkboxes."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "project_notif_email_enabled": "on",
            "project_notif_slack_enabled": "on",
            # telegram intentionally unchecked
            "project_notif_email_extra_to": "",
            "project_notif_telegram_override_chat_id": "",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert sorted(toml["notifications"]["channels"]) == ["email", "slack"]
    assert "telegram" not in toml["notifications"]["channels"]


# ---- Revision counts: one entry per top-level field changed -----------------


def test_settings_put_records_one_revision_per_top_level_field(
    settings_client, tmp_path
):
    """Saving data_paths + a model override → exactly 2 revision entries."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "data_paths": "x.csv",
            "model[task_agent]": "qwen3-coder",
            "endpoint[task_agent]": "private",
        },
    )
    revisions = json.loads((tmp_path / "alpha" / "revisions.json").read_text())[
        "revisions"
    ]
    fields = sorted(r["field"] for r in revisions)
    assert fields == ["data_paths", "runtime.models"]


def test_settings_put_no_changes_no_revisions(settings_client, tmp_path):
    """Submitting all-unchanged values writes no revisions."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    revisions_path = tmp_path / "alpha" / "revisions.json"
    if revisions_path.exists():
        revisions = json.loads(revisions_path.read_text())["revisions"]
        assert revisions == []


def test_settings_put_notifications_records_one_revision(settings_client, tmp_path):
    """Saving notifications changes records exactly one revision entry."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "project_notif_email_enabled": "on",
            # slack/telegram unchecked
            "project_notif_email_extra_to": "",
            "project_notif_telegram_override_chat_id": "",
        },
    )
    revisions = json.loads((tmp_path / "alpha" / "revisions.json").read_text())[
        "revisions"
    ]
    fields = [r["field"] for r in revisions]
    assert fields == ["notifications"]


# ---- Privacy tab: inherit / open / private / hybrid -------------------------


def _basics(**extra) -> dict:
    """Common required form fields for PUT /api/projects/<name>/settings."""
    base = {
        "question": "original q",
        "description": "orig desc",
        "mode": "exploratory",
        "audience": "expert",
    }
    base.update(extra)
    return base


def test_settings_put_privacy_inherit_no_longer_accepted(
    settings_client, tmp_path
):
    """The old 'inherit' value is rejected (422) — mode is required."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(project_privacy_mode="inherit"),
    )
    assert r.status_code == 422


def test_settings_put_privacy_private_writes_full_block(settings_client, tmp_path):
    """project_privacy_mode=private + url + model → [privacy] + endpoint subblock."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="http://localhost:11434",
            project_privacy_private_key_env="MY_KEY",
            project_privacy_private_model="qwen3:14b",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["privacy"]["mode"] == "private"
    assert (
        toml["privacy"]["endpoints"]["private"]["base_url"]
        == "http://localhost:11434"
    )
    assert toml["privacy"]["endpoints"]["private"]["api_key_env"] == "MY_KEY"


def test_settings_put_privacy_open_writes_mode_only(settings_client, tmp_path):
    """project_privacy_mode=open writes [privacy].mode='open' (no endpoints)."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="open",
            project_privacy_open_model="claude-sonnet-4-5",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["privacy"]["mode"] == "open"


def test_settings_put_privacy_hybrid_writes_both(settings_client, tmp_path):
    """Hybrid writes mode + private endpoint."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_cloud_model="claude-sonnet-4-5",
            project_privacy_hybrid_private_url="http://localhost:11434",
            project_privacy_hybrid_private_key_env="",
            project_privacy_hybrid_private_model="qwen3:14b",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["privacy"]["mode"] == "hybrid"
    assert (
        toml["privacy"]["endpoints"]["private"]["base_url"]
        == "http://localhost:11434"
    )


def test_settings_put_privacy_invalid_mode_returns_422(settings_client):
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(project_privacy_mode="bogus"),
    )
    assert r.status_code == 422


def test_settings_put_privacy_records_revision(settings_client, tmp_path):
    """Switching project privacy records exactly one revision entry."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="http://localhost:11434",
            project_privacy_private_model="qwen3:14b",
        ),
    )
    revisions = json.loads((tmp_path / "alpha" / "revisions.json").read_text())[
        "revisions"
    ]
    fields = [r["field"] for r in revisions]
    assert "privacy" in fields


# ---- Notifications tab: 2-state (enabled / disabled) per channel ------------


def _notif_basics(**extra) -> dict:
    """Common basics + the always-present hidden override text inputs."""
    base = _basics(
        project_notif_email_extra_to="",
        project_notif_telegram_override_chat_id="",
    )
    base.update(extra)
    return base


def test_settings_put_notifications_all_off_no_section(settings_client, tmp_path):
    """No channel checkbox set + no overrides → no [notifications] block."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "notifications" not in toml


def test_settings_put_notifications_email_enabled_writes_channel(
    settings_client, tmp_path
):
    """Email enabled at project level → [notifications].channels = ['email']."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(project_notif_email_enabled="on"),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["notifications"]["channels"] == ["email"]


def test_settings_put_notifications_extra_to_writes_email_table(
    settings_client, tmp_path
):
    """Email override with extra_to writes [notifications.email] with extra_to list."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(
            project_notif_email_enabled="on",
            project_notif_email_extra_to="alice@example.com, bob@example.com",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["notifications"]["email"]["extra_to"] == [
        "alice@example.com",
        "bob@example.com",
    ]


def test_settings_put_notifications_telegram_chat_id_override(
    settings_client, tmp_path
):
    """Telegram override with override_chat_id writes [notifications.telegram]."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(
            project_notif_telegram_enabled="on",
            project_notif_telegram_override_chat_id="999",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["notifications"]["telegram"]["override_chat_id"] == "999"


def test_settings_put_notifications_unchecked_excludes_channel(
    settings_client, tmp_path
):
    """An unchecked channel checkbox must NOT appear in the channels list."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(project_notif_slack_enabled="on"),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    notifs = toml.get("notifications", {})
    # Only slack — email and telegram unchecked.
    assert notifs.get("channels") == ["slack"]
    assert "email" not in notifs.get("channels", [])
    assert "telegram" not in notifs.get("channels", [])


def test_settings_put_notifications_no_disabled_sentinel(
    settings_client, tmp_path
):
    """The legacy ``_disabled`` sentinel list is no longer written."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(project_notif_email_enabled="on"),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    notifs = toml.get("notifications", {})
    assert "_disabled" not in notifs


def test_settings_put_notifications_toggle_off_clears_block(
    settings_client, tmp_path
):
    """Enabling a channel then unchecking it (no overrides) drops the block."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(project_notif_email_enabled="on"),
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "notifications" in toml

    settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(),  # no checkbox, no overrides
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "notifications" not in toml


def test_settings_put_notifications_overrides_persist_when_channel_off(
    settings_client, tmp_path
):
    """Per-channel overrides survive even when the channel itself is unchecked."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_notif_basics(
            # email checkbox NOT set, but extra_to is supplied
            project_notif_email_extra_to="alice@example.com",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    notifs = toml.get("notifications", {})
    # No channel listed (email not checked)
    assert notifs.get("channels", []) == []
    # But the override is preserved
    assert notifs["email"]["extra_to"] == ["alice@example.com"]


# ---- Commit 9: server-side endpoint constraint enforcement ----------------


def test_settings_put_models_private_mode_strips_open_endpoint(
    settings_client, tmp_path
):
    """In private mode, any per-agent endpoint=open is silently stripped.

    Defensive against form submissions that bypass the UI's restricted
    dropdown — the loader's runtime semantics make 'open' meaningless
    in private mode anyway.
    """
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="http://localhost:11434",
            **{
                "model[planning_agent]": "qwen3:14b",
                "endpoint[planning_agent]": "open",
            },
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    # endpoint=open is stripped; the model survives.
    pa = toml.get("runtime", {}).get("models", {}).get("planning_agent", {})
    assert pa.get("model") == "qwen3:14b"
    assert pa.get("endpoint") != "open"


def test_settings_put_models_hybrid_strips_open_for_data_agent(
    settings_client, tmp_path
):
    """In hybrid mode, data_agent's endpoint=open is silently stripped.

    data_agent is in the forced-private set (alongside tool_builder).
    """
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_private_url="http://localhost:11434",
            **{
                "model[data_agent]": "qwen3:14b",
                "endpoint[data_agent]": "open",
            },
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    da = toml.get("runtime", {}).get("models", {}).get("data_agent", {})
    assert da.get("model") == "qwen3:14b"
    assert da.get("endpoint") != "open"


def test_settings_put_models_hybrid_keeps_open_for_tool_builder(
    settings_client, tmp_path
):
    """In hybrid mode, tool_builder's endpoint=open is RESPECTED.
    Unlike data_agent, tool_builder isn't hard-locked private — the
    user is free to switch it to cloud."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_private_url="http://localhost:11434",
            **{
                "model[tool_builder]": "claude-opus-4-7",
                "endpoint[tool_builder]": "open",
            },
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    tb = toml.get("runtime", {}).get("models", {}).get("tool_builder", {})
    assert tb.get("endpoint") == "open"


def test_settings_put_models_hybrid_keeps_open_for_other_agents(
    settings_client, tmp_path
):
    """In hybrid mode, non-forced-private agents keep endpoint=open."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_private_url="http://localhost:11434",
            **{
                "model[planning_agent]": "claude-opus-4-7",
                "endpoint[planning_agent]": "open",
            },
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    pa = toml.get("runtime", {}).get("models", {}).get("planning_agent", {})
    assert pa.get("endpoint") == "open"


def test_settings_put_models_open_mode_keeps_open_endpoint(
    settings_client, tmp_path
):
    """In open mode, all agents may set endpoint=open (no stripping)."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="open",
            **{
                "model[data_agent]": "claude-opus-4-7",
                "endpoint[data_agent]": "open",
            },
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    da = toml.get("runtime", {}).get("models", {}).get("data_agent", {})
    assert da.get("endpoint") == "open"


# ---- Privacy mode-switch gate: requires endpoint somewhere -----------------
# Mirrors the POST /api/projects gate from Phase 12.6 commit 4. A project
# cannot switch to private/hybrid mode unless at least one usable private
# endpoint exists somewhere — project TOML, the form's URL, or globals.


@pytest.fixture
def settings_client_no_global_endpoint(tmp_path: Path, monkeypatch) -> TestClient:
    """settings_client variant with NO global private endpoint configured.

    Used to exercise the save-time gate that refuses private/hybrid
    mode when no endpoint is reachable from anywhere — the runtime
    would hard-fail otherwise.
    """
    proj = _write_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    # Intentionally NO settings.toml — no global endpoint available.
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_settings_put_private_blank_url_no_global_endpoint_returns_422(
    settings_client_no_global_endpoint,
):
    """Switching to private mode with a blank URL and no global endpoint
    must 422 — runtime would hard-fail with MissingPrivateEndpointError
    otherwise."""
    r = settings_client_no_global_endpoint.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="",
        ),
    )
    assert r.status_code == 422
    assert "endpoint" in r.json()["detail"].lower()


def test_settings_put_private_blank_url_with_global_endpoint_succeeds(
    settings_client,
):
    """settings_client pre-seeds a global private endpoint. With that
    in place, switching to private mode with a blank URL must succeed —
    the runtime loader inherits the endpoint from globals."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="",
        ),
    )
    assert r.status_code == 200


def test_settings_put_hybrid_blank_url_no_global_endpoint_returns_422(
    settings_client_no_global_endpoint,
):
    """Switching to hybrid mode with a blank URL and no global endpoint
    must 422 — data_agent and tool_builder are hard-locked private."""
    r = settings_client_no_global_endpoint.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_private_url="",
        ),
    )
    assert r.status_code == 422
    assert "endpoint" in r.json()["detail"].lower()


def test_settings_put_hybrid_blank_url_with_global_endpoint_succeeds(
    settings_client,
):
    """Hybrid + blank URL succeeds when globals supply an endpoint —
    the runtime loader inherits it."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_private_url="",
        ),
    )
    assert r.status_code == 200


def test_settings_put_open_mode_no_endpoint_required(
    settings_client_no_global_endpoint,
):
    """Open mode never needs a private endpoint — switching must
    succeed even without any endpoint defined anywhere."""
    r = settings_client_no_global_endpoint.put(
        "/api/projects/alpha/settings",
        data=_basics(project_privacy_mode="open"),
    )
    assert r.status_code == 200


# ---- Privacy block: blank URL + globals → skip project endpoint write ------
# When the form's URL field is blank AND a global endpoint exists, the
# project TOML must NOT carry [privacy.endpoints.private] — the runtime
# loader inherits from globals (commit 1). Stops the silent-stub-write
# behavior that left projects unrunnable.


def test_settings_put_private_blank_url_with_global_skips_endpoint_write(
    settings_client, tmp_path
):
    """Blank URL + global endpoint → project TOML has [privacy].mode but
    NO [privacy.endpoints]. The runtime loader fills in the endpoint via
    inheritance."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["privacy"]["mode"] == "private"
    # No project-local endpoint duplicate — inheritance handles it.
    assert "endpoints" not in toml["privacy"]


def test_settings_put_private_explicit_url_writes_override(
    settings_client, tmp_path
):
    """A non-blank URL becomes a project-local override that wins over
    globals (per the runtime loader's precedence rules)."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="http://my-server:8080",
            project_privacy_private_key_env="MY_KEY",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["privacy"]["mode"] == "private"
    assert (
        toml["privacy"]["endpoints"]["private"]["base_url"]
        == "http://my-server:8080"
    )


def test_settings_put_hybrid_blank_url_with_global_skips_endpoint_write(
    settings_client, tmp_path
):
    """Same rule for hybrid mode: blank URL + globals → no project-local
    [privacy.endpoints] written."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="hybrid",
            project_privacy_hybrid_private_url="",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["privacy"]["mode"] == "hybrid"
    assert "endpoints" not in toml["privacy"]


# ---- Privacy tab page render: shows inheritance hint -----------------------


def test_project_settings_page_shows_inherited_endpoint_when_globals_exist(
    settings_client,
):
    """The project Privacy tab renders an 'Inherits global endpoint' line
    above the per-mode URL inputs when globals supply an endpoint."""
    r = settings_client.get("/projects/alpha/settings")
    assert r.status_code == 200
    body = r.text
    # Inheritance hint must appear in the page somewhere — both private
    # and hybrid blocks reuse the same wording.
    assert "Inherits global endpoint" in body
    # The global endpoint URL the test fixture seeded.
    assert "http://localhost:11434" in body


def test_project_settings_page_no_inherit_hint_without_globals(
    settings_client_no_global_endpoint,
):
    """When globals have no endpoint, the inheritance hint must NOT
    appear (it would mislead the user about what's inherited)."""
    r = settings_client_no_global_endpoint.get("/projects/alpha/settings")
    assert r.status_code == 200
    assert "Inherits global endpoint" not in r.text
