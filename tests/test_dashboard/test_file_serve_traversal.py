"""Path-traversal guards on dashboard file-serve routes.

The code defends against ``..``, leading ``/``, and (for the artifact
route) embedded slashes, but only the /respond endpoint's traversal
guard had a regression test before this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "?"\nmode = "exploratory"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "artifacts").mkdir(parents=True)
    (exp_dir / "artifacts" / "plot.png").write_bytes(b"\x89PNG")
    (exp_dir / "presentation").mkdir()
    (exp_dir / "presentation" / "index.html").write_text("<html>ok</html>")
    (exp_dir / "presentation" / "style.css").write_text("body{}")
    (proj / "projectbook").mkdir(exist_ok=True)
    (proj / "projectbook" / "findings.json").write_text(json.dumps({"answer": "ok"}))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


# ── /experiments/{exp_id}/artifacts/{filename} ─────────────────


def test_artifact_serves_safe_filename(client) -> None:
    r = client.get("/projects/alpha/experiments/exp-001/artifacts/plot.png")
    assert r.status_code == 200


def test_artifact_traversal_with_dotdot_400s(client) -> None:
    r = client.get("/projects/alpha/experiments/exp-001/artifacts/..%2Furika.toml")
    assert r.status_code in (400, 404), r.text


def test_artifact_traversal_with_slash_400s(client) -> None:
    # FastAPI URL-decodes ``%2F`` to ``/`` before reaching the handler.
    r = client.get("/projects/alpha/experiments/exp-001/artifacts/sub%2Fdir%2Ffile.txt")
    assert r.status_code in (400, 404), r.text


def test_artifact_unknown_filename_404s(client) -> None:
    r = client.get("/projects/alpha/experiments/exp-001/artifacts/missing.png")
    assert r.status_code == 404


# ── /experiments/{exp_id}/presentation/{rest:path} ─────────────


def test_presentation_asset_serves_safe(client) -> None:
    r = client.get("/projects/alpha/experiments/exp-001/presentation/style.css")
    assert r.status_code == 200


def test_presentation_asset_dotdot_400s(client) -> None:
    r = client.get("/projects/alpha/experiments/exp-001/presentation/../urika.toml")
    # Either 400 (caught explicitly), 404 (resolved-outside check), or
    # 422 (FastAPI path-param rejection) — must NOT be 200.
    assert r.status_code != 200


def test_presentation_asset_absolute_leading_slash_400s(client) -> None:
    """Leading-slash ``rest`` is explicitly rejected by the guard at
    pages.py:1824."""
    r = client.get("/projects/alpha/experiments/exp-001/presentation//etc/passwd")
    assert r.status_code in (400, 404)


def test_presentation_asset_empty_rest_400s(client) -> None:
    """``rest`` must be non-empty (the guard at pages.py:1824 includes
    `not rest`)."""
    # Trailing slash with empty rest → may route differently; if it
    # gets to the handler it returns 400.
    r = client.get("/projects/alpha/experiments/exp-001/presentation/")
    # Either 400, 404, or 301/307 redirect — never 200.
    assert r.status_code != 200


# ── /api/projects/{name}/runs/{exp_id}/respond — ensure existing
# regression still holds across routes ─────────────────────────


def test_respond_endpoint_rejects_traversal(client, tmp_path) -> None:
    """Belt-and-braces: confirm the /respond endpoint that already had
    a traversal test still rejects ``..`` (regression chain — if a
    refactor breaks one route's defense, the others should hold)."""
    # /respond requires a prompt_id (file under prompts/) — try a
    # traversal prompt_id.
    r = client.post(
        "/api/projects/alpha/runs/exp-001/respond",
        json={"prompt_id": "../etc/passwd", "value": "x"},
    )
    # 400 (traversal guard), 404 (prompt-id not found), 422 (schema
    # rejection) — never 200.
    assert r.status_code != 200
