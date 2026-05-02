"""Tests for GET /api/projects/<name>/artifacts/projectbook — Phase B5.2.

Read-only on-disk probe. Reports whether the project-level summary,
report, presentation, and findings artifacts exist under
``<project>/projectbook``. Used by the summarize / finalize live log
pages to reveal "view the result" CTAs only once the relevant file
has actually been written. Mirrors the per-experiment artifact probe
at ``/api/projects/<n>/experiments/<id>/artifacts``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project(root: Path, name: str = "alpha") -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q for {name}"\n'
        f'mode = "exploratory"\ndescription = ""\n\n'
        f'[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def book_client(tmp_path: Path, monkeypatch) -> TestClient:
    proj = _make_project(tmp_path, "alpha")
    # Empty projectbook dir — every flag should come back False.
    (proj / "projectbook").mkdir()

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


def test_404_unknown_project(book_client):
    r = book_client.get("/api/projects/nonexistent/artifacts/projectbook")
    assert r.status_code == 404


def test_returns_all_false_for_empty_projectbook(book_client):
    r = book_client.get("/api/projects/alpha/artifacts/projectbook")
    assert r.status_code == 200
    data = r.json()
    assert data == {
        "has_summary": False,
        "has_report": False,
        "has_presentation": False,
        "has_findings": False,
    }


def test_returns_true_when_artifacts_exist(tmp_path: Path, monkeypatch):
    """All four flags flip to True when their backing files exist —
    presentation in the directory form (presentation/index.html)."""
    proj = _make_project(tmp_path, "alpha")
    book = proj / "projectbook"
    book.mkdir()
    (book / "summary.md").write_text("# Summary\n")
    (book / "report.md").write_text("# Report\n")
    (book / "findings.json").write_text(json.dumps({"best_method": "ols"}))
    pres_dir = book / "presentation"
    pres_dir.mkdir()
    (pres_dir / "index.html").write_text("<html></html>")

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.get("/api/projects/alpha/artifacts/projectbook")
    assert r.status_code == 200
    data = r.json()
    assert data == {
        "has_summary": True,
        "has_report": True,
        "has_presentation": True,
        "has_findings": True,
    }


def test_presentation_final_presentation_dir(tmp_path: Path, monkeypatch):
    """Regression (v0.4.1): `urika finalize` writes the project-level
    deck to ``projectbook/final-presentation/index.html``, but the
    artifact probe was only checking ``projectbook/presentation/``
    — so a finalized project showed no Presentation card on the
    project home and no "view the result" CTA on the finalize log
    page. Probe must now accept the final-presentation/ directory
    too.
    """
    proj = _make_project(tmp_path, "alpha")
    book = proj / "projectbook"
    (book / "final-presentation").mkdir(parents=True)
    (book / "final-presentation" / "index.html").write_text(
        "<html><body>final deck</body></html>"
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.get("/api/projects/alpha/artifacts/projectbook")
    assert r.status_code == 200
    data = r.json()
    assert data["has_presentation"] is True


def test_presentation_either_form(tmp_path: Path, monkeypatch):
    """has_presentation must accept the single-file form
    (projectbook/presentation.html) just as it accepts the
    directory form (projectbook/presentation/index.html)."""
    proj = _make_project(tmp_path, "alpha")
    book = proj / "projectbook"
    book.mkdir()
    (book / "presentation.html").write_text("<html></html>")
    # Other artifacts deliberately absent so we isolate the flag.

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.get("/api/projects/alpha/artifacts/projectbook")
    assert r.status_code == 200
    data = r.json()
    assert data["has_presentation"] is True
    # And the others stay False.
    assert data["has_summary"] is False
    assert data["has_report"] is False
    assert data["has_findings"] is False
