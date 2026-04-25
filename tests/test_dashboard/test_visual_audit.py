"""Lightweight assertions that key pages render with design-system markers.

Each main page should:
  - Load the bundled stylesheet (so design-system tokens are present).
  - Use only modifier-suffixed buttons (`.btn--primary`, `.btn--ghost`, …).
    A bare `<button class="btn">` or `<a class="btn">` has no color rules
    and renders as an invisible/gray box.
  - Use the canonical `.breadcrumb-separator` class (not the older
    `.breadcrumb-sep`, which has no CSS).
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


# ---- shared regex helpers -------------------------------------------------

# Match <button class="btn"> or <a class="btn"> with NO modifier suffix.
# We accept attributes before/after class but require the class value to be
# exactly "btn" (possibly surrounded by whitespace) — i.e. no `btn--*` and
# no other classes that would carry the design-system modifier.
_BARE_BTN_RE = re.compile(
    r'<(?:button|a)\b[^>]*\bclass="\s*btn\s*"[^>]*>',
    re.IGNORECASE,
)


def _assert_design_system(body: str) -> None:
    """Common assertions: stylesheet loaded, no bare `.btn`, no broken sep."""
    assert "/static/app.css" in body, "page does not load the design system CSS"
    bare = _BARE_BTN_RE.findall(body)
    assert bare == [], f"Found bare .btn buttons (no modifier): {bare}"
    # The older `.breadcrumb-sep` class has no CSS rule; standardize on
    # `.breadcrumb-separator`.
    assert "breadcrumb-sep\"" not in body, (
        "page uses the deprecated `breadcrumb-sep` class; "
        "use `breadcrumb-separator` instead"
    )


# ---- fixtures -------------------------------------------------------------


def _make_minimal(root: Path, name: str) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def audit_client(tmp_path: Path, monkeypatch) -> TestClient:
    """One project with one experiment + runs + methods + knowledge."""
    proj = _make_minimal(tmp_path, "alpha")

    # experiment + progress
    exp_id = "exp-001"
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
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "status": "completed",
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

    # methods
    (proj / "methods.json").write_text(
        json.dumps(
            {
                "methods": [
                    {
                        "name": "ols",
                        "description": "linear",
                        "script": "ols.py",
                        "experiment": exp_id,
                        "turn": 1,
                        "metrics": {"r2": 0.5},
                        "status": "active",
                    },
                ]
            }
        )
    )

    # knowledge
    knowledge_dir = proj / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": "k-001",
                        "source": "/tmp/paper.pdf",
                        "source_type": "pdf",
                        "title": "A paper",
                        "content": "body",
                        "tags": [],
                        "added_at": "2026-04-25T00:00:00Z",
                    }
                ]
            }
        )
    )

    # registry
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    return TestClient(app)


# ---- tests ----------------------------------------------------------------


def test_projects_list_uses_design_system(audit_client):
    r = audit_client.get("/projects")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_project_home_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_experiments_page_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/experiments")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_experiment_detail_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_methods_page_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/methods")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_knowledge_page_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/knowledge")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_knowledge_entry_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/knowledge/k-001")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_run_page_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/run")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_run_log_page_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_project_settings_page_uses_design_system(audit_client):
    r = audit_client.get("/projects/alpha/settings")
    assert r.status_code == 200
    _assert_design_system(r.text)


def test_global_settings_page_uses_design_system(settings_client):
    r = settings_client.get("/settings")
    assert r.status_code == 200
    _assert_design_system(r.text)


# ---- dark mode swap -------------------------------------------------------


def test_app_css_defines_dark_theme_swap():
    """The stylesheet must define both root and `[data-theme="dark"]` tokens."""
    from urika.dashboard.app import create_app

    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/static/app.css")
    assert r.status_code == 200
    body = r.text
    assert ":root" in body
    assert '[data-theme="dark"]' in body


def test_theme_toggle_lives_in_sidebar_not_header(audit_client):
    r = audit_client.get("/projects")
    body = r.text
    # The theme toggle button has the .theme-toggle class.
    # It must appear inside the <aside class="sidebar"> block, not
    # inside <header class="page-header">.
    sidebar_match = re.search(
        r'<aside class="sidebar"[^>]*>(.*?)</aside>', body, re.DOTALL
    )
    assert sidebar_match is not None
    assert 'theme-toggle' in sidebar_match.group(1)
    # And NOT in the page-header
    header_match = re.search(
        r'<header class="page-header"[^>]*>(.*?)</header>', body, re.DOTALL
    )
    if header_match:
        assert 'theme-toggle' not in header_match.group(1)
