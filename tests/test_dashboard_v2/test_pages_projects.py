from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


@pytest.fixture
def client_with_projects(tmp_path: Path, monkeypatch) -> TestClient:
    """A dashboard whose registry is forced to point at tmp projects."""
    # Fabricate two projects on disk
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        proj.mkdir()
        (proj / "urika.toml").write_text(
            f'[project]\n'
            f'name = "{name}"\n'
            f'question = "q for {name}"\n'
            f'mode = "exploratory"\n'
            f'description = ""\n'
            f'\n'
            f'[preferences]\n'
            f'audience = "expert"\n'
        )

    # Force the ProjectRegistry to read from a tmp file
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({
        "alpha": str(tmp_path / "alpha"),
        "beta": str(tmp_path / "beta"),
    }))

    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_root_redirects_to_projects(client_with_projects: TestClient):
    r = client_with_projects.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/projects"


def test_projects_list_shows_all_projects(client_with_projects: TestClient):
    r = client_with_projects.get("/projects")
    assert r.status_code == 200
    body = r.text
    assert "alpha" in body
    assert "beta" in body
    assert "q for alpha" in body


def test_projects_list_empty_state(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/projects")
    assert r.status_code == 200
    assert "No projects" in r.text or "No projects yet" in r.text
