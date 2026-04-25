"""Tests for POST /api/projects (synchronous workspace creation).

Materializes a project workspace on disk, writes urika.toml, and
registers the project in the central registry. Builder-agent
invocation is deferred — this endpoint just lays down the scaffolding.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def create_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    """A dashboard client wired to a tmp URIKA_HOME and tmp projects_root.

    Mirrors the settings_client pattern: empty project registry, a
    settings.toml that sets ``projects_root`` to a tmp directory, and
    a TestClient bound to ``create_app(project_root=tmp_path)``.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")

    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    settings_path = home / "settings.toml"
    settings_path.write_text(
        f'projects_root = "{projects_root}"\n', encoding="utf-8"
    )

    app = create_app(project_root=tmp_path)
    return TestClient(app), projects_root


# ---- Happy path ------------------------------------------------------------


def test_create_project_materializes_workspace_and_registers(create_client, tmp_path):
    client, projects_root = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "my-project",
            "question": "Does X predict Y?",
            "description": "A short description.",
            "data_paths": "/path/to/data.csv\n/path/to/other.csv",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "my-project"
    project_dir = Path(body["path"])
    assert project_dir == projects_root / "my-project"

    # urika.toml is on disk with the right fields
    toml_path = project_dir / "urika.toml"
    assert toml_path.exists()
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    assert data["project"]["name"] == "my-project"
    assert data["project"]["question"] == "Does X predict Y?"
    assert data["project"]["mode"] == "exploratory"
    assert data["project"]["data_paths"] == [
        "/path/to/data.csv",
        "/path/to/other.csv",
    ]
    assert data["preferences"]["audience"] == "expert"

    # Standard subdirs were created
    for subdir in ("data", "experiments", "knowledge", "projectbook"):
        assert (project_dir / subdir).is_dir()

    # Registered in the central registry
    registry = json.loads((tmp_path / "home" / "projects.json").read_text())
    assert registry == {"my-project": str(project_dir)}


def test_create_project_htmx_returns_hx_redirect(create_client):
    """An HTMX request gets a 201 + HX-Redirect header pointing at the project home."""
    client, _ = create_client
    r = client.post(
        "/api/projects",
        headers={"hx-request": "true"},
        data={
            "name": "alpha-proj",
            "question": "How does feedback shape motor learning?",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 201
    assert r.headers.get("hx-redirect") == "/projects/alpha-proj"


# ---- Validation errors -----------------------------------------------------


def test_create_project_invalid_name_returns_422(create_client):
    """Names must be lowercase alphanumeric + hyphens, not starting with -."""
    client, _ = create_client
    # Underscores are forbidden
    r = client.post(
        "/api/projects",
        data={
            "name": "Bad_Name",
            "question": "q",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 422

    # Leading hyphen is forbidden
    r = client.post(
        "/api/projects",
        data={
            "name": "-leading-hyphen",
            "question": "q",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 422

    # Empty name fails
    r = client.post(
        "/api/projects",
        data={
            "name": "",
            "question": "q",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 422


def test_create_project_invalid_mode_returns_422(create_client):
    client, _ = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "proj",
            "question": "q",
            "mode": "garbage",
            "audience": "expert",
        },
    )
    assert r.status_code == 422


def test_create_project_invalid_audience_returns_422(create_client):
    """audience must be one of {'expert', 'novice'} — 'standard' is not valid."""
    client, _ = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "proj",
            "question": "q",
            "mode": "exploratory",
            "audience": "standard",
        },
    )
    assert r.status_code == 422


def test_create_project_missing_question_returns_422(create_client):
    client, _ = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "proj",
            "question": "",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 422


# ---- Conflict / duplicate --------------------------------------------------


def test_create_project_duplicate_name_returns_409(create_client):
    """A second create with the same name fails after the registry sees it."""
    client, _ = create_client
    payload = {
        "name": "dup-proj",
        "question": "q",
        "mode": "exploratory",
        "audience": "expert",
    }
    r1 = client.post("/api/projects", data=payload)
    assert r1.status_code == 201

    r2 = client.post("/api/projects", data=payload)
    assert r2.status_code == 409
