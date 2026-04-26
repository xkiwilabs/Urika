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


# ---- Notifications auto_enable seeding ------------------------------------


def test_create_project_seeds_auto_enabled_channels(tmp_path: Path, monkeypatch):
    """Channels with global ``auto_enable=true`` get seeded into the new
    project's [notifications].channels list. Channels with
    ``auto_enable=false`` (or unset) stay out."""
    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")

    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    settings_toml = home / "settings.toml"
    settings_toml.write_text(
        f'projects_root = "{projects_root}"\n\n'
        "[notifications.email]\n"
        'from_addr = "x@y.com"\n'
        "auto_enable = true\n\n"
        "[notifications.slack]\n"
        'channel = "#x"\n'
        "auto_enable = false\n",
        encoding="utf-8",
    )

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects",
        data={
            "name": "auto-test",
            "question": "Q?",
            "description": "",
            "mode": "exploratory",
            "audience": "expert",
            "data_paths": "",
        },
    )
    assert r.status_code == 201
    proj_toml = tomllib.loads(
        (projects_root / "auto-test" / "urika.toml").read_text(encoding="utf-8")
    )
    assert proj_toml["notifications"]["channels"] == ["email"]
    assert "slack" not in proj_toml["notifications"]["channels"]


def test_create_project_no_auto_enable_no_notifications_block(create_client):
    """When no channel has ``auto_enable=true`` (the default), the new
    project's urika.toml has no [notifications] block at all."""
    client, projects_root = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "no-notif",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 201
    proj_toml = tomllib.loads(
        (projects_root / "no-notif" / "urika.toml").read_text(encoding="utf-8")
    )
    # No global auto_enable flags → no channels seeded.
    assert "notifications" not in proj_toml or "channels" not in proj_toml.get(
        "notifications", {}
    )


# ---- Privacy mode validation ----------------------------------------------


def test_create_project_privacy_mode_private_without_endpoint_returns_422(
    create_client,
):
    """Picking privacy_mode=private with no global endpoint configured
    must 422 — otherwise the runtime would raise
    MissingPrivateEndpointError on first agent call."""
    client, _ = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "no-ep-priv",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "privacy_mode": "private",
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"].lower()
    assert "private" in detail
    assert "endpoint" in detail
    assert "privacy" in detail or "/settings" in detail


def test_create_project_privacy_mode_hybrid_without_endpoint_returns_422(
    create_client,
):
    """Hybrid mode is symmetric — data agents are forced-private."""
    client, _ = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "no-ep-hyb",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "privacy_mode": "hybrid",
        },
    )
    assert r.status_code == 422


def test_create_project_invalid_privacy_mode_returns_422(create_client):
    """Garbage privacy_mode values are rejected up front."""
    client, _ = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "bad-priv",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "privacy_mode": "garbage",
        },
    )
    assert r.status_code == 422


def test_create_project_privacy_mode_private_with_endpoint_succeeds(
    tmp_path: Path, monkeypatch
):
    """When a private endpoint is configured globally, private/hybrid
    POSTs are accepted. The new project's urika.toml carries the
    [privacy].mode override."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    settings_path = home / "settings.toml"
    settings_path.write_text(
        f'projects_root = "{projects_root}"\n'
        "[privacy.endpoints.private]\n"
        'base_url = "http://localhost:11434"\n',
        encoding="utf-8",
    )

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects",
        data={
            "name": "priv-ok",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "privacy_mode": "private",
        },
    )
    assert r.status_code == 201, r.text

    # The project's urika.toml should have [privacy].mode = "private".
    proj_toml = tomllib.loads(
        (projects_root / "priv-ok" / "urika.toml").read_text(encoding="utf-8")
    )
    assert proj_toml["privacy"]["mode"] == "private"


def test_create_project_privacy_mode_open_default_does_not_gate(create_client):
    """When privacy_mode is omitted or set to ``open``, the endpoint
    check is skipped (cloud is always available)."""
    client, projects_root = create_client
    r = client.post(
        "/api/projects",
        data={
            "name": "open-default",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            # Note: no privacy_mode field
        },
    )
    assert r.status_code == 201

    # No [privacy] block written for open mode.
    proj_toml = tomllib.loads(
        (projects_root / "open-default" / "urika.toml").read_text(
            encoding="utf-8"
        )
    )
    assert "privacy" not in proj_toml or "mode" not in proj_toml.get(
        "privacy", {}
    )


def test_create_project_privacy_mode_endpoint_with_blank_url_does_not_pass(
    tmp_path: Path, monkeypatch
):
    """An endpoint section defined with a blank base_url is NOT a
    valid private endpoint. The 422 must still fire — same rule as the
    runtime loader's MissingPrivateEndpointError."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    settings_path = home / "settings.toml"
    settings_path.write_text(
        f'projects_root = "{projects_root}"\n'
        "[privacy.endpoints.private]\n"
        'base_url = ""\n',
        encoding="utf-8",
    )

    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects",
        data={
            "name": "blank-url",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "privacy_mode": "private",
        },
    )
    assert r.status_code == 422


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
