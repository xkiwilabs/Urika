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
        f'[project]\n'
        f'name = "{name}"\n'
        f'question = "original q"\n'
        f'mode = "exploratory"\n'
        f'description = "orig desc"\n'
        f'\n'
        f'[preferences]\n'
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
