from pathlib import Path

from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


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


def test_projects_list_has_new_project_button_and_modal(
    client_with_projects: TestClient,
):
    """The /projects page exposes a + New project action that opens a
    modal carrying the create-project form.
    """
    body = client_with_projects.get("/projects").text
    # Top-right action button
    assert "+ New project" in body
    assert "open-modal" in body
    assert "'id': 'new-project'" in body or '"id": "new-project"' in body or (
        "id: 'new-project'" in body
    )
    # Modal posts to the create endpoint via HTMX
    assert 'hx-post="/api/projects"' in body
    # Required form fields
    for field_name in ("name", "question", "description", "data_paths", "mode", "audience"):
        assert f'name="{field_name}"' in body, f"missing form field: {field_name}"
    # Mode and audience dropdowns are populated from valid_modes / valid_audiences
    assert ">exploratory<" in body
    assert ">expert<" in body


def test_projects_list_renders_search_and_sort(client_with_projects: TestClient):
    r = client_with_projects.get("/projects")
    body = r.text
    assert 'class="list-search"' in body
    assert 'class="list-sort"' in body
    assert "Recent activity" in body


def test_project_summary_has_last_activity(tmp_path: Path):
    from urika.dashboard.projects import list_project_summaries
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    summaries = list_project_summaries({"alpha": proj})
    assert summaries[0].last_activity != ""
    assert "T" in summaries[0].last_activity  # ISO format
