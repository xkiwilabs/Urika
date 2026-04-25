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
    """[notifications].channels list is written from per-channel state radios."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data={
            "question": "original q",
            "description": "orig desc",
            "mode": "exploratory",
            "audience": "expert",
            "project_notif_email_state": "enabled",
            "project_notif_slack_state": "enabled",
            "project_notif_telegram_state": "inherit",
        },
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert sorted(toml["notifications"]["channels"]) == ["email", "slack"]


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
            "project_notif_email_state": "enabled",
            "project_notif_slack_state": "inherit",
            "project_notif_telegram_state": "inherit",
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


def test_settings_put_privacy_inherit_writes_no_section(settings_client, tmp_path):
    """project_privacy_mode=inherit → no [privacy] block in urika.toml."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(project_privacy_mode="inherit"),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "privacy" not in toml


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


def test_settings_put_privacy_switch_back_to_inherit_clears_block(
    settings_client, tmp_path
):
    """Setting an override then switching to inherit removes [privacy] entirely."""
    # First write a private override
    settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_privacy_mode="private",
            project_privacy_private_url="http://localhost:11434",
            project_privacy_private_model="qwen3:14b",
        ),
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "privacy" in toml

    # Now switch back to inherit — block should be removed
    settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(project_privacy_mode="inherit"),
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "privacy" not in toml


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


# ---- Notifications tab: per-channel inherit / enable / disable --------------


def test_settings_put_notifications_all_inherit_no_section(settings_client, tmp_path):
    """All channels inherit → no [notifications] block in urika.toml."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_notif_email_state="inherit",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="inherit",
        ),
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
        data=_basics(
            project_notif_email_state="enabled",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="inherit",
        ),
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
        data=_basics(
            project_notif_email_state="enabled",
            project_notif_email_extra_to="alice@example.com, bob@example.com",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="inherit",
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
        data=_basics(
            project_notif_email_state="inherit",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="enabled",
            project_notif_telegram_override_chat_id="999",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert toml["notifications"]["telegram"]["override_chat_id"] == "999"


def test_settings_put_notifications_disabled_excludes_channel(
    settings_client, tmp_path
):
    """Channel set to 'disabled' must NOT appear in channels list."""
    r = settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_notif_email_state="disabled",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="inherit",
        ),
    )
    assert r.status_code == 200
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    notifs = toml.get("notifications", {})
    # Email is disabled (override saying "off") and shouldn't be in channels.
    assert "email" not in notifs.get("channels", [])
    # The block exists since we wrote a disabled override.
    assert "notifications" in toml


def test_settings_put_notifications_switch_back_to_inherit_clears_block(
    settings_client, tmp_path
):
    """Setting an override then switching all to inherit removes [notifications]."""
    settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_notif_email_state="enabled",
            project_notif_email_extra_to="alice@example.com",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="inherit",
        ),
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "notifications" in toml

    settings_client.put(
        "/api/projects/alpha/settings",
        data=_basics(
            project_notif_email_state="inherit",
            project_notif_slack_state="inherit",
            project_notif_telegram_state="inherit",
        ),
    )
    toml = tomllib.loads((tmp_path / "alpha" / "urika.toml").read_text())
    assert "notifications" not in toml
