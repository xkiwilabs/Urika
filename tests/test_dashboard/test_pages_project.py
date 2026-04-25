from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project_with_experiments(root: Path, name: str, n_exps: int):
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f"[project]\n"
        f'name = "{name}"\n'
        f'question = "q for {name}"\n'
        f'mode = "exploratory"\n'
        f'description = ""\n'
        f"\n"
        f"[preferences]\n"
        f'audience = "expert"\n'
    )
    for i in range(n_exps):
        exp_id = f"exp-{i + 1:03d}"
        exp_dir = proj / "experiments" / exp_id
        exp_dir.mkdir(parents=True)
        (exp_dir / "experiment.json").write_text(
            json.dumps(
                {
                    "experiment_id": exp_id,
                    "name": f"experiment {i + 1}",
                    "hypothesis": f"hypothesis {i + 1}",
                    "status": "completed",
                    "created_at": f"2026-04-{i + 1:02d}T00:00:00Z",
                }
            )
        )
    return proj


@pytest.fixture
def client_with_experiments(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_experiments(tmp_path, "alpha", 7)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_project_home_returns_200_and_shows_name_and_question(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    assert "alpha" in r.text
    assert "q for alpha" in r.text


def test_project_home_404_for_unknown(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent")
    assert r.status_code == 404


def test_project_home_lists_recent_experiments(client_with_experiments):
    r = client_with_experiments.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # 7 experiments created; recent 5 should be exp-003 through exp-007.
    # Most recent first, so exp-007 listed first.
    assert "exp-007" in body
    assert "exp-006" in body
    assert "exp-005" in body
    assert "exp-004" in body
    assert "exp-003" in body
    # exp-001 and exp-002 should NOT appear (they're outside the top-5)
    assert "exp-001" not in body
    assert "exp-002" not in body


def test_project_home_sidebar_shows_project_links(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    # Sidebar has project-scoped Home/Experiments/Methods/Knowledge/Run/Settings links
    assert "/projects/alpha/experiments" in body
    assert "/projects/alpha/methods" in body
    assert "/projects/alpha/knowledge" in body
    assert "/projects/alpha/run" in body
    assert "/projects/alpha/settings" in body


def test_experiments_page_returns_200_and_shows_experiments(client_with_experiments):
    r = client_with_experiments.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # All 7 experiments visible (this page shows the full list, not just top 5)
    for i in range(1, 8):
        assert f"exp-{i:03d}" in body


def test_experiments_page_404_for_unknown(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/experiments")
    assert r.status_code == 404


def test_experiments_page_empty_state(client_with_projects):
    """alpha in client_with_projects has no experiment dirs."""
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert "No experiments yet" in body or "no experiments" in body.lower()


def _make_project_with_runs(root: Path, name: str, exp_id: str, n_runs: int) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q for {name}"\n'
        f'mode = "exploratory"\ndescription = ""\n\n'
        f'[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "name": "baseline",
                "hypothesis": "linear models will fit",
                "status": "completed",
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )
    runs = [
        {
            "run_id": f"run-{i + 1:03d}",
            "method": "ols",
            "params": {},
            "metrics": {"r2": 0.5 + i * 0.01},
            "observation": f"observation for run {i + 1}",
            "timestamp": f"2026-04-25T0{i}:00:00Z",
        }
        for i in range(n_runs)
    ]
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "status": "completed",
                "runs": runs,
            }
        )
    )
    return proj


@pytest.fixture
def client_with_runs(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_runs(tmp_path, "alpha", "exp-001", 3)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_experiment_detail_returns_200_and_shows_hypothesis(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert "linear models will fit" in body
    assert "exp-001" in body


def test_experiment_detail_lists_runs(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "ols" in body  # method name
    assert "run-001" in body or "observation for run 1" in body


def test_experiment_detail_404_for_unknown_experiment(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-999")
    assert r.status_code == 404


def test_experiment_detail_404_for_unknown_project(client_with_runs):
    r = client_with_runs.get("/projects/nonexistent/experiments/exp-001")
    assert r.status_code == 404


def _make_project_with_methods(root: Path, name: str, methods: list[dict]) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    (proj / "methods.json").write_text(json.dumps({"methods": methods}))
    return proj


@pytest.fixture
def client_with_methods(tmp_path: Path, monkeypatch) -> TestClient:
    methods = [
        {
            "name": "ols",
            "description": "linear",
            "script": "ols.py",
            "experiment": "exp-001",
            "turn": 1,
            "metrics": {"r2": 0.5},
            "status": "active",
        },
        {
            "name": "rf",
            "description": "forest",
            "script": "rf.py",
            "experiment": "exp-001",
            "turn": 2,
            "metrics": {"r2": 0.8},
            "status": "active",
        },
    ]
    _make_project_with_methods(tmp_path, "alpha", methods)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_methods_page_returns_200_and_lists_methods(client_with_methods):
    r = client_with_methods.get("/projects/alpha/methods")
    assert r.status_code == 200
    body = r.text
    # Methods are server-rendered into the DOM, no JSON dump.
    assert "ols" in body
    assert "rf" in body


def test_methods_page_does_not_embed_raw_json(client_with_methods):
    """The methods page must not leak a JSON dump of the methods list.

    Previously the template embedded ``{{ methods | tojson }}`` so Alpine
    could sort client-side; that put the entire methods list as JSON in
    page source. The replacement server-renders rows with data-sort-*
    attributes, so no JSON dump should appear.
    """
    r = client_with_methods.get("/projects/alpha/methods")
    assert r.status_code == 200
    body = r.text
    # Distinctive substrings only present in a JSON dump of the methods.
    assert '"description":' not in body
    assert '"metrics":' not in body
    assert '"script":' not in body
    assert '"experiment":' not in body


def test_methods_page_404_unknown_project(client_with_methods):
    r = client_with_methods.get("/projects/nonexistent/methods")
    assert r.status_code == 404


def test_methods_page_empty_state(client_with_projects):
    r = client_with_projects.get("/projects/alpha/methods")
    assert r.status_code == 200
    assert "No methods registered yet" in r.text or "no methods" in r.text.lower()


def _make_project_with_knowledge(root: Path, name: str, entries: list[dict]) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    knowledge_dir = proj / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "index.json").write_text(json.dumps({"entries": entries}))
    return proj


@pytest.fixture
def client_with_knowledge(tmp_path: Path, monkeypatch) -> TestClient:
    entries = [
        {
            "id": "k-001",
            "source": "/tmp/paper.pdf",
            "source_type": "pdf",
            "title": "A neural net paper",
            "content": "# title\n\nbody body body",
            "tags": [],
            "added_at": "2026-04-25T00:00:00Z",
        },
        {
            "id": "k-002",
            "source": "https://example.com/article",
            "source_type": "url",
            "title": "An article",
            "content": "url content",
            "tags": [],
            "added_at": "2026-04-25T01:00:00Z",
        },
    ]
    _make_project_with_knowledge(tmp_path, "alpha", entries)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_knowledge_page_returns_200_and_lists_entries(client_with_knowledge):
    r = client_with_knowledge.get("/projects/alpha/knowledge")
    assert r.status_code == 200
    body = r.text
    assert "A neural net paper" in body
    assert "An article" in body
    assert "k-001" in body
    assert "pdf" in body


def test_knowledge_entry_page_renders_content(client_with_knowledge):
    r = client_with_knowledge.get("/projects/alpha/knowledge/k-001")
    assert r.status_code == 200
    body = r.text
    assert "A neural net paper" in body
    assert "body body body" in body  # raw content visible


def test_knowledge_entry_404_unknown_id(client_with_knowledge):
    r = client_with_knowledge.get("/projects/alpha/knowledge/k-999")
    assert r.status_code == 404


def test_knowledge_page_empty_state(client_with_projects):
    r = client_with_projects.get("/projects/alpha/knowledge")
    assert r.status_code == 200
    assert "No knowledge ingested yet" in r.text or "no knowledge" in r.text.lower()


def test_knowledge_page_404_unknown_project(client_with_knowledge):
    r = client_with_knowledge.get("/projects/nonexistent/knowledge")
    assert r.status_code == 404


def _make_project_minimal(root: Path, name: str) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def client_run_no_active(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_minimal(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def client_run_active(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _make_project_minimal(tmp_path, "alpha")
    # Fabricate a running experiment
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / ".lock").write_text("12345")  # PID, contents not important
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_run_page_returns_form_when_no_active_experiment(client_run_no_active):
    r = client_run_no_active.get("/projects/alpha/run")
    assert r.status_code == 200
    body = r.text
    assert 'name="name"' in body
    assert 'name="hypothesis"' in body
    assert 'name="mode"' in body
    assert 'name="audience"' in body
    assert 'name="max_turns"' in body
    assert 'hx-post="/api/projects/alpha/run"' in body


def test_run_page_shows_view_live_link_when_active(client_run_active):
    r = client_run_active.get("/projects/alpha/run")
    assert r.status_code == 200
    body = r.text
    assert "exp-001" in body
    assert "/projects/alpha/experiments/exp-001/log" in body
    # Form should NOT be shown
    assert 'hx-post="/api/projects/alpha/run"' not in body


def test_run_page_404_unknown_project(client_run_no_active):
    r = client_run_no_active.get("/projects/nonexistent/run")
    assert r.status_code == 404


def test_run_log_page_returns_200_and_has_eventsource(client_run_active):
    r = client_run_active.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    body = r.text
    assert "EventSource" in body
    # SSE URL embedded in the inline script
    assert "/api/projects/alpha/runs/exp-001/stream" in body
    # Pre element to receive log lines
    assert 'id="log"' in body


def test_run_log_page_404_unknown_project(client_run_active):
    r = client_run_active.get("/projects/nonexistent/experiments/exp-001/log")
    assert r.status_code == 404


def test_run_log_page_works_without_existing_experiment(client_run_no_active):
    """Loading the log page right after a POST /api/projects/.../run is
    valid even before the experiment dir has any output."""
    r = client_run_no_active.get("/projects/alpha/experiments/exp-future/log")
    # Project exists; the page itself doesn't validate the experiment id —
    # SSE handles the no-data case.
    assert r.status_code == 200


def test_report_view_renders_markdown(client_with_runs):
    # Fabricate report.md
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text("# Findings\n\nLinear models fit best.")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/report")
    assert r.status_code == 200
    assert "<h1>Findings</h1>" in r.text
    assert "Linear models fit best." in r.text


def test_report_view_404_when_no_report(client_with_runs):
    """exp-001 has no report.md by default in this fixture."""
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/report")
    assert r.status_code == 404


def test_report_view_404_unknown_experiment(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-999/report")
    assert r.status_code == 404


def test_presentation_view_serves_html_file(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "presentation.html").write_text(
        "<!DOCTYPE html><html><body>fake reveal deck</body></html>"
    )
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/presentation")
    assert r.status_code == 200
    assert "fake reveal deck" in r.text
    # Served as text/html, not wrapped in our base template
    assert '<aside class="sidebar"' not in r.text


def test_presentation_view_404_when_missing(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/presentation")
    assert r.status_code == 404


def test_report_view_rewrites_relative_image_paths(client_with_runs):
    """Markdown like ``![](fig.png)`` should resolve to the artifact viewer URL."""
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    artifacts_dir = exp_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "fig.png").write_bytes(b"\x89PNGfake")
    (exp_dir / "report.md").write_text(
        "# Findings\n\n![Figure 1](fig.png)\n\n![Figure 2](artifacts/fig.png)\n"
    )
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/report")
    assert r.status_code == 200
    body = r.text
    # Both forms should resolve to the same absolute artifact URL.
    assert (
        'src="/projects/alpha/experiments/exp-001/artifacts/fig.png"' in body
    )
    # The unrewritten relative forms should NOT be in the page.
    assert 'src="fig.png"' not in body
    assert 'src="artifacts/fig.png"' not in body


def test_report_view_leaves_absolute_urls_alone(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text(
        "[Link](https://example.com/page)\n\n"
        "![Remote](https://example.com/x.png)\n"
    )
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/report")
    body = r.text
    assert 'href="https://example.com/page"' in body
    assert 'src="https://example.com/x.png"' in body


def test_experiment_presentation_serves_reveal_css(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "experiments" / "exp-001" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html></html>")
    (pres_dir / "reveal.css").write_text("body { color: red }")
    r = client_with_runs.get(
        "/projects/alpha/experiments/exp-001/presentation/reveal.css"
    )
    assert r.status_code == 200
    assert "color: red" in r.text


def test_experiment_presentation_serves_reveal_js(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "experiments" / "exp-001" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html></html>")
    (pres_dir / "reveal.min.js").write_text("// reveal js content")
    r = client_with_runs.get(
        "/projects/alpha/experiments/exp-001/presentation/reveal.min.js"
    )
    assert r.status_code == 200
    assert "reveal js content" in r.text


def test_experiment_presentation_serves_subdirectory_figures(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "experiments" / "exp-001" / "presentation"
    figures = pres_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html></html>")
    (figures / "fig.png").write_bytes(b"\x89PNGdata")
    r = client_with_runs.get(
        "/projects/alpha/experiments/exp-001/presentation/figures/fig.png"
    )
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_experiment_presentation_rejects_traversal(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "experiments" / "exp-001" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html></html>")
    r = client_with_runs.get(
        "/projects/alpha/experiments/exp-001/presentation/..%2F..%2Fetc%2Fpasswd"
    )
    assert r.status_code in (400, 404)


def test_projectbook_presentation_serves_assets(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "projectbook" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html></html>")
    (pres_dir / "reveal.css").write_text("body{}")
    r = client_with_runs.get("/projects/alpha/projectbook/presentation/reveal.css")
    assert r.status_code == 200
    assert "body{}" in r.text


def test_existing_presentation_root_still_works(client_with_runs):
    """The bare ``/presentation`` route should still serve ``index.html``."""
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "experiments" / "exp-001" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html><body>deck</body></html>")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/presentation")
    assert r.status_code == 200
    assert "deck" in r.text


def test_artifact_file_viewer_serves_png(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    artifacts_dir = proj / "experiments" / "exp-001" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "fig.png").write_bytes(b"\x89PNGfake")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/artifacts/fig.png")
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_artifact_file_viewer_rejects_traversal(client_with_runs):
    r = client_with_runs.get(
        "/projects/alpha/experiments/exp-001/artifacts/..%2F..%2Fetc%2Fpasswd"
    )
    # FastAPI URL-decodes path params, so this becomes "../../etc/passwd"
    # but our slash/.. check rejects it.
    assert r.status_code in (400, 404)


def test_experiment_detail_shows_report_button_when_present(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text("# Findings")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "View report" in body
    assert "/projects/alpha/experiments/exp-001/report" in body


def test_experiment_detail_shows_generate_buttons_when_artifacts_missing(
    client_with_runs,
):
    """When report.md / presentation.html aren't there, show 'Generate'
    buttons that POST to the relevant agent endpoint."""
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "Generate report" in body or "Run finalize" in body
    assert "Generate presentation" in body or "Run present" in body


def test_experiment_detail_lists_artifacts(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    artifacts_dir = proj / "experiments" / "exp-001" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "fig1.png").write_bytes(b"fake")
    (artifacts_dir / "table.csv").write_text("a,b")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "fig1.png" in body
    assert "table.csv" in body


def test_experiment_detail_presentation_link_opens_new_tab(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    (proj / "experiments" / "exp-001" / "presentation.html").write_text("<html></html>")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    # The presentation link must open in a new tab
    import re

    m = re.search(
        r'<a[^>]*href="/projects/alpha/experiments/exp-001/presentation"[^>]*>',
        body,
    )
    assert m is not None
    assert 'target="_blank"' in m.group(0)


def test_findings_page_renders_well_known_fields(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "findings.json").write_text(
        json.dumps(
            {
                "question": "Which features predict X?",
                "answer": "Linear models fit best.",
                "final_methods": [
                    {
                        "name": "ols",
                        "role": "primary_prediction",
                        "script": "methods/final_ols.py",
                        "key_metrics": {"r2": 0.9},
                        "summary": "Linear regression.",
                    },
                    {
                        "name": "rf",
                        "role": "robustness",
                        "script": "methods/final_rf.py",
                        "key_metrics": {"r2": 0.8},
                        "summary": "Random forest.",
                    },
                ],
                "limitations": ["Small sample size"],
            }
        )
    )
    r = client_with_runs.get("/projects/alpha/findings")
    assert r.status_code == 200
    body = r.text
    assert "Linear models fit best." in body
    assert "Which features predict X?" in body
    assert "ols" in body
    assert "Small sample size" in body
    # NO JSON dump of well-known keys.
    assert '"answer":' not in body
    assert '"final_methods":' not in body
    assert '"limitations":' not in body


def test_findings_page_renders_unknown_keys_as_more_block(client_with_runs):
    """Keys not in the well-known set still render — but as formatted
    HTML inside a 'More' details block, never as raw JSON."""
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "findings.json").write_text(
        json.dumps(
            {
                "answer": "OK.",
                "weird_string": "a custom note",
                "weird_list": ["alpha", "beta"],
                "weird_dict": {"k1": "v1", "k2": "v2"},
            }
        )
    )
    r = client_with_runs.get("/projects/alpha/findings")
    assert r.status_code == 200
    body = r.text
    # Well-known answer rendered as a paragraph.
    assert "OK." in body
    # Unknown key values appear as text (not JSON).
    assert "a custom note" in body
    assert "alpha" in body
    assert "beta" in body
    assert "v1" in body
    assert "v2" in body
    # Key labels are humanised in the More block.
    assert "weird_string" in body or "Weird string" in body
    # NEVER raw JSON.
    assert '"weird_string":' not in body
    assert '"weird_list":' not in body
    assert '"weird_dict":' not in body
    # The More block is a <details> element.
    assert "<details" in body


def test_findings_page_404_when_no_findings(client_with_runs):
    """exp-001 has no findings.json by default in this fixture."""
    r = client_with_runs.get("/projects/alpha/findings")
    assert r.status_code == 404


def test_findings_page_404_unknown_project(client_with_runs):
    r = client_with_runs.get("/projects/nonexistent/findings")
    assert r.status_code == 404


def test_project_home_links_to_findings_when_present(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "findings.json").write_text(json.dumps({"answer": "done"}))
    r = client_with_runs.get("/projects/alpha")
    assert r.status_code == 200
    assert "/projects/alpha/findings" in r.text


def test_project_home_does_not_link_to_findings_when_absent(client_with_runs):
    r = client_with_runs.get("/projects/alpha")
    assert r.status_code == 200
    assert "/projects/alpha/findings" not in r.text


def test_project_home_shows_final_outputs_when_present(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "findings.json").write_text("{}")
    (book / "report.md").write_text("# Final report")
    (book / "presentation.html").write_text("<html></html>")
    r = client_with_runs.get("/projects/alpha")
    body = r.text
    assert "Final outputs" in body
    assert "/projects/alpha/findings" in body
    assert "/projects/alpha/projectbook/report" in body or "Final report" in body
    assert "/projects/alpha/projectbook/presentation" in body or "presentation" in body


def test_project_home_final_outputs_card_omitted_when_no_artifacts(client_with_runs):
    """When none of findings/report/presentation exist, the section is hidden."""
    r = client_with_runs.get("/projects/alpha")
    assert r.status_code == 200
    assert "Final outputs" not in r.text


def test_project_home_final_outputs_renders_only_present_cards(client_with_runs):
    """Only cards for artifacts that exist should render."""
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    # Only findings.json is present.
    (book / "findings.json").write_text("{}")
    r = client_with_runs.get("/projects/alpha")
    body = r.text
    assert "Final outputs" in body
    assert "/projects/alpha/findings" in body
    # Report and presentation cards should NOT be rendered.
    assert "/projects/alpha/projectbook/report" not in body
    assert "/projects/alpha/projectbook/presentation" not in body


def test_projectbook_report_renders_markdown(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "report.md").write_text("# Final write-up\n\nProject summary here.")
    r = client_with_runs.get("/projects/alpha/projectbook/report")
    assert r.status_code == 200
    assert "<h1>Final write-up</h1>" in r.text
    assert "Project summary here." in r.text


def test_projectbook_report_404_when_missing(client_with_runs):
    r = client_with_runs.get("/projects/alpha/projectbook/report")
    assert r.status_code == 404


def test_projectbook_report_404_unknown_project(client_with_runs):
    r = client_with_runs.get("/projects/nonexistent/projectbook/report")
    assert r.status_code == 404


def test_projectbook_presentation_serves_html(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "presentation.html").write_text(
        "<!DOCTYPE html><html><body>final deck</body></html>"
    )
    r = client_with_runs.get("/projects/alpha/projectbook/presentation")
    assert r.status_code == 200
    assert "final deck" in r.text
    # Served raw, not wrapped in our base template.
    assert '<aside class="sidebar"' not in r.text


def test_projectbook_presentation_serves_directory_index(client_with_runs):
    """Also accept presentation/index.html (directory form)."""
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "projectbook" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body>dir-form deck</body></html>"
    )
    r = client_with_runs.get("/projects/alpha/projectbook/presentation")
    assert r.status_code == 200
    assert "dir-form deck" in r.text


def test_projectbook_presentation_404_when_missing(client_with_runs):
    r = client_with_runs.get("/projects/alpha/projectbook/presentation")
    assert r.status_code == 404


def test_projectbook_presentation_404_unknown_project(client_with_runs):
    r = client_with_runs.get("/projects/nonexistent/projectbook/presentation")
    assert r.status_code == 404


# --- Bug 1: live status overlay (progress.json wins over experiment.json) ---

def _make_project_with_pending_exp(root: Path, name: str, exp_id: str) -> Path:
    """Fixture helper: experiment.json says 'pending' (the default), but
    progress.json says 'completed' — what the live state actually is."""
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q for {name}"\n'
        f'mode = "exploratory"\ndescription = ""\n\n'
        f'[preferences]\naudience = "expert"\n'
    )
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "name": "baseline",
                "hypothesis": "h",
                "status": "pending",  # default, never overwritten
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "status": "completed",  # the live status
                "runs": [
                    {
                        "run_id": "run-001",
                        "method": "ols",
                        "params": {},
                        "metrics": {"r2": 0.5},
                        "observation": "obs",
                        "timestamp": "2026-04-25T00:00:00Z",
                    }
                ],
            }
        )
    )
    return proj


@pytest.fixture
def client_with_pending_exp(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_pending_exp(tmp_path, "alpha", "exp-001")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_experiments_list_uses_progress_status_when_present(client_with_pending_exp):
    """progress.json's status overrides experiment.json's pending default."""
    r = client_with_pending_exp.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # The live status should be visible
    assert "completed" in body
    # The stale 'pending' from experiment.json must NOT leak through
    assert 'tag tag--pending' not in body


def test_experiment_detail_uses_progress_status_when_present(client_with_pending_exp):
    r = client_with_pending_exp.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert "completed" in body
    assert 'tag tag--pending' not in body


# --- Bug 2: directory-form presentation detection ---

def test_experiment_detail_recognizes_directory_form_presentation(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    pres_dir = exp_dir / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text("<html></html>")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    # Should show "Open presentation" (artifact present), not "Generate presentation"
    assert "Open presentation" in body
    assert "Generate presentation" not in body


# --- Bug 3: humanize filter applied in templates ---

def test_experiments_list_humanizes_experiment_names(client_with_runs):
    """Experiment 'baseline' should appear humanized as 'Baseline' in the list."""
    r = client_with_runs.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # client_with_runs fixture creates name="baseline" — humanize → "Baseline"
    assert "Baseline" in body
