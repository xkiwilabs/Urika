def test_api_projects_returns_json_list(client_with_projects):
    r = client_with_projects.get("/api/projects")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    names = {p["name"] for p in data}
    assert names == {"alpha", "beta"}
    for p in data:
        assert "question" in p
        assert "mode" in p
        assert "experiment_count" in p


def test_api_projects_empty_when_no_registry(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from urika.dashboard_v2.app import create_app
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert r.json() == []
