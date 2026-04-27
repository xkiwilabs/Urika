"""Tests for DELETE /api/projects/<name>/experiments/<exp_id>.

Mirrors the URIKA_HOME monkeypatch + create_app(project_root) pattern
used in test_api_delete_project.py. Each test redirects URIKA_HOME into
``tmp_path / 'home'`` so the deletion log doesn't touch the real
``~/.urika``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    (proj / "experiments").mkdir()
    return proj


def _make_experiment(proj: Path, exp_id: str = "exp-001") -> Path:
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps({"experiment_id": exp_id, "name": "test"})
    )
    (exp_dir / "code").mkdir()
    return exp_dir


@pytest.fixture
def home_with_alpha_exp(tmp_path: Path, monkeypatch):
    """Register ``alpha`` with one experiment ``exp-001``."""
    proj = _make_project(tmp_path, "alpha")
    exp = _make_experiment(proj, "exp-001")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), proj, exp, home


def test_delete_unknown_project_returns_404(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    client = TestClient(create_app(project_root=tmp_path))

    r = client.delete("/api/projects/ghost/experiments/exp-001")
    assert r.status_code == 404
    assert r.json()["detail"] == "Unknown project"


def test_delete_unknown_experiment_returns_422(home_with_alpha_exp):
    client, _proj, _exp, _home = home_with_alpha_exp

    r = client.delete("/api/projects/alpha/experiments/exp-missing")
    assert r.status_code == 422
    assert r.json()["detail"] == "Unknown experiment"


def test_delete_with_active_lock_returns_422(home_with_alpha_exp):
    import os

    client, _proj, exp, _home = home_with_alpha_exp
    lock = exp / ".lock"
    # Use the test process's PID so the lock is detected as live.
    lock.write_text(str(os.getpid()))

    r = client.delete("/api/projects/alpha/experiments/exp-001")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert str(lock) in detail
    # Experiment untouched
    assert exp.exists()


def test_delete_success_returns_payload(home_with_alpha_exp):
    client, proj, exp, _home = home_with_alpha_exp

    r = client.delete("/api/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.json()
    assert body["experiment_id"] == "exp-001"
    assert isinstance(body["trash_path"], str)
    # Trash dir lives under <project>/trash/
    assert body["trash_path"].startswith(str(proj / "trash"))

    # Original experiment dir gone, trash dir exists.
    assert not exp.exists()
    assert Path(body["trash_path"]).exists()
    # Project survives
    assert proj.exists()


def test_delete_hx_request_returns_hx_redirect(home_with_alpha_exp):
    client, _proj, _exp, _home = home_with_alpha_exp

    r = client.delete(
        "/api/projects/alpha/experiments/exp-001",
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/experiments"


def test_delete_appends_deletion_log(home_with_alpha_exp):
    client, _proj, _exp, home = home_with_alpha_exp

    r = client.delete("/api/projects/alpha/experiments/exp-001")
    assert r.status_code == 200

    log = home / "deletion-log.jsonl"
    assert log.exists()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "experiment"
    assert record["project_name"] == "alpha"
    assert record["experiment_id"] == "exp-001"
