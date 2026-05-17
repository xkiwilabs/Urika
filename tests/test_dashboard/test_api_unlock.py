"""Dashboard ``POST /api/projects/{name}/experiments/{exp_id}/unlock``
parity test (v0.4.5 D2).

Pre-v0.4.5 the dashboard only had ``/active-ops/clear-stale`` which
removed *dead-PID* locks. The ``--force`` path that recovers from a
live-but-recycled PID was CLI-only. This endpoint closes that gap
so a stuck dashboard project can be unstuck without dropping to a
shell.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_project(tmp_path: Path, monkeypatch):
    """Boot the dashboard's TestClient with an isolated URIKA_HOME +
    a single registered project containing one experiment. Matches
    the existing fixture pattern in
    ``tests/test_dashboard/conftest.py``: ``create_app`` takes a
    ``project_root`` and the registry is seeded by writing
    ``projects.json`` directly."""
    import json

    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace
    from urika.dashboard.app import create_app

    home = tmp_path / "urika-home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    create_experiment(proj, name="baseline", hypothesis="h")
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    return TestClient(app), proj


def test_unknown_project_404(app_with_project) -> None:
    client, _proj = app_with_project
    r = client.post("/api/projects/does-not-exist/experiments/exp-001-baseline/unlock")
    assert r.status_code == 404


def test_no_lock_returns_no_lock_status(app_with_project) -> None:
    """No lock file present → 200 with status="no_lock". This is
    the idempotent case the UI gets when the user clicks Unlock
    on a row that's already cleaned."""
    client, _proj = app_with_project
    r = client.post("/api/projects/alpha/experiments/exp-001-baseline/unlock")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no_lock"


def test_dead_pid_lock_auto_cleared(app_with_project) -> None:
    """Lock pointing at an obviously-dead PID → cleared without
    needing ``force``. Mirrors the CLI's
    ``test_dead_pid_lock_is_cleaned_and_run_proceeds``."""
    client, proj = app_with_project
    lock = proj / "experiments" / "exp-001-baseline" / ".lock"
    lock.write_text("99999998")  # implausibly large; psutil reports dead

    r = client.post("/api/projects/alpha/experiments/exp-001-baseline/unlock")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cleared"
    assert not lock.exists()


def test_live_urika_lock_refused_without_force(app_with_project, monkeypatch) -> None:
    """Live PID + urika-looking process name → 409 with status
    ``refused_live_urika``. Body's ``detail`` carries the structured
    payload the UI uses to decide what to show in the confirm
    modal."""
    client, proj = app_with_project
    lock = proj / "experiments" / "exp-001-baseline" / ".lock"
    lock.write_text("12345")

    monkeypatch.setattr("urika.core.session._pid_is_alive", lambda p: True)
    monkeypatch.setattr("urika.core.session._get_process_name", lambda p: "python")

    r = client.post("/api/projects/alpha/experiments/exp-001-baseline/unlock")
    assert r.status_code == 409
    body = r.json()
    detail = body["detail"]
    assert detail["status"] == "refused_live_urika"
    assert detail["pid"] == 12345
    assert detail["proc_name"] == "python"
    assert lock.exists(), "refused unlock must not remove the lock"


def test_live_urika_lock_force_unlocks(app_with_project, monkeypatch) -> None:
    """Same live-PID setup but with ``{"force": true}`` body →
    200 with status="cleared". Confirms the override path works
    so a user with a confirmed-recycled PID can recover."""
    client, proj = app_with_project
    lock = proj / "experiments" / "exp-001-baseline" / ".lock"
    lock.write_text("12345")

    monkeypatch.setattr("urika.core.session._pid_is_alive", lambda p: True)
    monkeypatch.setattr("urika.core.session._get_process_name", lambda p: "python")

    r = client.post(
        "/api/projects/alpha/experiments/exp-001-baseline/unlock",
        json={"force": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cleared"
    assert not lock.exists()


def test_live_non_urika_pid_returns_refused_live_other(
    app_with_project, monkeypatch
) -> None:
    """A live PID whose process name DOESN'T look like urika is
    classified as ``refused_live_other`` — almost certainly a
    recycled PID. Wizard / UI shows a different confirm message in
    that case (per the experiments.html JS)."""
    client, proj = app_with_project
    lock = proj / "experiments" / "exp-001-baseline" / ".lock"
    lock.write_text("12345")

    monkeypatch.setattr("urika.core.session._pid_is_alive", lambda p: True)
    monkeypatch.setattr("urika.core.session._get_process_name", lambda p: "bash")

    r = client.post("/api/projects/alpha/experiments/exp-001-baseline/unlock")
    assert r.status_code == 409
    body = r.json()
    detail = body["detail"]
    assert detail["status"] == "refused_live_other"
    assert detail["proc_name"] == "bash"
