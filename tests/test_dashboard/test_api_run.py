"""Tests for POST /api/projects/<name>/run.

Spawns are stubbed via monkeypatch so the tests never invoke a
real ``urika run`` subprocess. We assert: (a) the experiment dir
is materialized on disk, (b) the spawn helper was called with
the right args, and (c) JSON vs HTMX response shaping behaves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard import runs as runs_module
from urika.dashboard.app import create_app


def _make_project(tmp_path: Path, name: str = "alpha") -> Path:
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def run_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, list[dict], Path]:
    proj = _make_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, experiment_id, **kwargs):
        spawn_calls.append(
            {
                "project_name": project_name,
                "project_path": project_path,
                "experiment_id": experiment_id,
                **kwargs,
            }
        )
        # Simulate the daemon thread's first writes
        exp_dir = project_path / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / ".lock").write_text("99999")
        (exp_dir / "run.log").write_text("Spawned\n")
        return 99999

    monkeypatch.setattr(runs_module, "spawn_experiment_run", fake_spawn)
    # Also patch the symbol where the API router imported it from
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_experiment_run", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_run_post_creates_experiment_and_spawns(run_client):
    client, spawn_calls, proj = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["pid"] == 99999
    exp_id = body["experiment_id"]
    # Experiment dir exists
    assert (proj / "experiments" / exp_id / "experiment.json").exists()
    # Lock file written by fake spawn
    assert (proj / "experiments" / exp_id / ".lock").read_text() == "99999"
    # Spawn was called with the right args
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["project_name"] == "alpha"
    assert spawn_calls[0]["experiment_id"] == exp_id
    assert spawn_calls[0]["project_path"] == proj


def test_run_post_forwards_optional_flags_to_spawn(run_client):
    """instructions, max_turns, audience from the form must be
    forwarded to spawn_experiment_run so the spawned ``urika run``
    subprocess receives them. Previously dropped on the floor — the
    form fields were validated but discarded, leaving the CLI to
    re-discover values from project state instead."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "7",
            "instructions": "focus on regularized models",
        },
    )
    assert r.status_code == 200
    assert len(spawn_calls) == 1
    call = spawn_calls[0]
    assert call.get("instructions") == "focus on regularized models"
    assert call.get("max_turns") == 7
    assert call.get("audience") == "expert"


def test_run_post_forwards_advanced_flags(run_client):
    """Advanced toggles (auto/max_experiments/review_criteria) from the
    modal must be forwarded as kwargs to spawn_experiment_run so the
    spawned ``urika run`` subprocess receives the right CLI flags.

    Resume is intentionally NOT in this set — it's a per-experiment
    action exposed on the experiments list (failed/paused/stopped
    rows get their own Resume button → POST /experiments/<id>/resume),
    not a "new experiment" option."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "be thorough",
            "auto": "on",
            "max_experiments": "3",
            "review_criteria": "on",
        },
    )
    assert r.status_code == 200
    assert spawn_calls
    call = spawn_calls[0]
    assert call.get("auto") is True
    assert call.get("max_experiments") == 3
    assert call.get("review_criteria") is True
    # /run never sets resume — the new-experiment modal doesn't carry it.
    assert call.get("resume") is False


def test_run_post_max_experiments_without_auto_returns_422(run_client):
    """max_experiments only takes effect in autonomous mode — supplying
    it without ``auto`` must 422 rather than silently dropping the flag."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
            "max_experiments": "3",  # without auto
        },
    )
    assert r.status_code == 422
    assert spawn_calls == []


def test_run_post_advanced_flags_default_false(run_client):
    """When the advanced section is left collapsed, the spawn helper sees
    auto=False / max_experiments=None / review_criteria=False / resume=False."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    assert spawn_calls
    call = spawn_calls[0]
    assert call.get("auto") is False
    assert call.get("max_experiments") is None
    assert call.get("review_criteria") is False
    assert call.get("resume") is False


def test_run_post_invalid_max_experiments_returns_422(run_client):
    """Non-positive / non-integer max_experiments must 422."""
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
            "auto": "on",
            "max_experiments": "0",
        },
    )
    assert r.status_code == 422


def test_run_post_returns_html_fragment_by_default(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    assert "View live log" in r.text


def test_run_post_returns_hx_redirect_when_htmx_request(run_client):
    """The "+ New experiment" modal posts via HTMX. On success the API
    must respond with HX-Redirect so the browser navigates the whole
    page to the live log instead of swapping a fragment into the modal.
    """
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"hx-request": "true"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    redirect = r.headers.get("hx-redirect", "")
    assert redirect.startswith("/projects/alpha/experiments/")
    assert redirect.endswith("/log")


def test_run_post_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/nonexistent/run",
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 404


def test_run_post_invalid_max_turns(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "-1",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_post_non_integer_max_turns(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "not-a-number",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_run_post_invalid_audience(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "alien",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 422


def test_new_experiment_form_no_longer_requires_name_or_hypothesis(run_client):
    """The redesigned + New experiment modal matches ``urika run``: no
    name, no hypothesis, no mode. POST without those fields must succeed
    — the planning agent populates name/hypothesis during the run, and
    mode is project-level, not per-experiment."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    assert len(spawn_calls) == 1


def test_run_stop_writes_flag(run_client):
    client, _, proj = run_client
    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stop_requested"
    assert body["experiment_id"] == "exp-001"
    flag_path = proj / ".urika" / "pause_requested"
    assert flag_path.exists()
    assert flag_path.read_text() == "stop"


def test_run_stop_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post("/api/projects/nonexistent/runs/exp-001/stop")
    assert r.status_code == 404


def test_run_stop_creates_dotdir_if_missing(run_client):
    """The .urika dir doesn't exist by default; the endpoint must mkdir it."""
    client, _, proj = run_client
    assert not (proj / ".urika").exists()
    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    assert (proj / ".urika").is_dir()


# ---- POST /api/projects/<n>/runs/<exp_id>/respond (Task 11F.2) ------------


def test_run_respond_writes_answer_file(run_client):
    client, _, proj = run_client
    r = client.post(
        "/api/projects/alpha/runs/exp-001/respond",
        data={"prompt_id": "p-001", "answer": "Use OLS"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answer_recorded"
    assert body["prompt_id"] == "p-001"
    answer_path = proj / "experiments" / "exp-001" / ".prompts" / "p-001.answer"
    assert answer_path.exists()
    assert answer_path.read_text() == "Use OLS"


def test_run_respond_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/nonexistent/runs/exp-001/respond",
        data={"prompt_id": "p-001", "answer": "x"},
    )
    assert r.status_code == 404


def test_run_respond_422_missing_prompt_id(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/runs/exp-001/respond",
        data={"prompt_id": "", "answer": "x"},
    )
    assert r.status_code == 422


def test_run_respond_400_traversal(run_client):
    client, _, _ = run_client
    r = client.post(
        "/api/projects/alpha/runs/exp-001/respond",
        data={"prompt_id": "../../etc/passwd", "answer": "x"},
    )
    assert r.status_code == 400


def test_run_respond_creates_dotdir_if_missing(run_client):
    client, _, proj = run_client
    assert not (proj / "experiments" / "exp-001" / ".prompts").exists()
    r = client.post(
        "/api/projects/alpha/runs/exp-001/respond",
        data={"prompt_id": "p-001", "answer": "x"},
    )
    assert r.status_code == 200
    assert (proj / "experiments" / "exp-001" / ".prompts").is_dir()


# ---- Privacy pre-flight check ---------------------------------------------


def _make_private_project(tmp_path: Path, name: str = "alpha") -> Path:
    """Make a project with [privacy].mode = private but no endpoint."""
    proj = tmp_path / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n\n'
        f'[privacy]\nmode = "private"\n'
    )
    return proj


@pytest.fixture
def run_client_private_no_endpoint(
    tmp_path: Path, monkeypatch
) -> tuple[TestClient, list[dict], Path]:
    """A run-client whose project is in private mode but with no
    private endpoint configured anywhere — runs must be refused."""
    proj = _make_private_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    # Empty settings.toml — no private endpoint defined globally.
    (home / "settings.toml").write_text("", encoding="utf-8")

    spawn_calls: list[dict] = []

    def fake_spawn(project_name, project_path, experiment_id, **_):
        spawn_calls.append(
            {
                "project_name": project_name,
                "experiment_id": experiment_id,
            }
        )
        return 1234

    monkeypatch.setattr(runs_module, "spawn_experiment_run", fake_spawn)
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_experiment_run", fake_spawn)

    app = create_app(project_root=tmp_path)
    return TestClient(app), spawn_calls, proj


def test_run_post_private_mode_without_endpoint_returns_422(
    run_client_private_no_endpoint,
):
    """Pre-flight gate: project in private mode + no endpoint must
    fail before the experiment dir is created and before spawn is
    called."""
    client, spawn_calls, proj = run_client_private_no_endpoint
    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"].lower()
    assert "private" in detail
    assert "endpoint" in detail
    # Spawn must NOT have been called.
    assert spawn_calls == []
    # No experiment dir created.
    exp_root = proj / "experiments"
    if exp_root.exists():
        assert list(exp_root.iterdir()) == []


def test_run_post_private_mode_with_endpoint_succeeds(tmp_path: Path, monkeypatch):
    """Symmetric positive case: when a global endpoint is configured,
    private-mode projects can run."""
    proj = _make_private_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    (home / "settings.toml").write_text(
        '[privacy.endpoints.private]\nbase_url = "http://localhost:11434"\n',
        encoding="utf-8",
    )

    def fake_spawn(project_name, project_path, experiment_id, **_):
        exp_dir = project_path / "experiments" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / ".lock").write_text("99999")
        return 99999

    monkeypatch.setattr(runs_module, "spawn_experiment_run", fake_spawn)
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(api_module, "spawn_experiment_run", fake_spawn)

    app = create_app(project_root=tmp_path)
    client = TestClient(app)

    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200, r.text


# ---- Idempotent spawn: redirect to live log when already running ---------


def test_run_post_when_already_running_redirects_to_log(run_client):
    """HTMX POST while a run is already in flight on this project must
    NOT spawn a duplicate experiment. Instead, redirect to the live log."""
    import os

    client, spawn_calls, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / ".lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/run",
        headers={"hx-request": "true"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/experiments/exp-001/log"
    assert spawn_calls == []
    # No new experiment dir created either.
    other = [d for d in (proj / "experiments").iterdir() if d.name != "exp-001"]
    assert other == []


def test_run_post_when_already_running_returns_409_without_hx(run_client):
    """Non-HTMX caller (curl, scripts) must get a 409 with a JSON body
    so they can detect the duplicate explicitly instead of a 200."""
    import os

    client, spawn_calls, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / ".lock").write_text(str(os.getpid()))

    r = client.post(
        "/api/projects/alpha/run",
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "already_running"
    assert body["log_url"] == "/projects/alpha/experiments/exp-001/log"
    assert body["type"] == "run"
    assert spawn_calls == []


def test_run_post_other_experiment_stale_lock_does_not_block(run_client):
    """A *stale* run lock (dead PID) on a different experiment must NOT
    block a fresh run — only live locks count as ``already running``.
    Verifies the running-op check filters by ``_is_active_run_lock``
    rather than mere lock-file presence.
    """
    client, spawn_calls, proj = run_client
    other = proj / "experiments" / "exp-OTHER"
    other.mkdir(parents=True, exist_ok=True)
    (other / "experiment.json").write_text("{}")
    # PID 99999999 is virtually guaranteed not to be a live process.
    (other / ".lock").write_text("99999999")

    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
        },
    )
    assert r.status_code == 200
    assert len(spawn_calls) == 1


def test_run_post_default_mode_succeeds_with_no_extras(run_client):
    """Pressing Run with no advanced options changed must just work.
    Bug fix: the modal's Max-experiments input was hidden via x-show
    when Auto was unchecked but still submitted its default value (5),
    causing the server to 422 on
    ``max_experiments requires --auto``. The modal now disables the
    input when Auto is off so it's excluded from the form payload —
    pin that contract here at the API layer."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "10",
            "instructions": "",
            # Auto unchecked → max_experiments not submitted at all.
        },
    )
    assert r.status_code == 200
    assert len(spawn_calls) == 1
    call = spawn_calls[0]
    assert call.get("auto") is False
    assert call.get("max_experiments") is None


def test_run_post_auto_unlimited_translates_to_high_cap(run_client):
    """``auto_limit=unlimited`` → server sends a high max_experiments
    cap to the CLI so meta-orchestrator runs in unlimited mode (CLI
    sets ``meta_mode = "unlimited" if auto`` only when
    --max-experiments is set)."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "10",
            "instructions": "",
            "auto": "on",
            "auto_limit": "unlimited",
        },
    )
    assert r.status_code == 200
    call = spawn_calls[0]
    assert call.get("auto") is True
    assert call.get("max_experiments") == 999  # large effective cap


# ---- POST /experiments/<id>/resume ----


def test_resume_post_spawns_run_with_resume_flag(run_client):
    """Resume on a per-experiment row spawns ``urika run --experiment
    <id> --resume`` for that experiment, and HX-Redirects to its log."""
    client, spawn_calls, proj = run_client
    exp = proj / "experiments" / "exp-001"
    exp.mkdir(parents=True, exist_ok=True)
    (exp / "experiment.json").write_text("{}")

    r = client.post(
        "/api/projects/alpha/experiments/exp-001/resume",
        headers={"hx-request": "true"},
    )
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/projects/alpha/experiments/exp-001/log"
    assert len(spawn_calls) == 1
    call = spawn_calls[0]
    assert call.get("experiment_id") == "exp-001"
    assert call.get("resume") is True


def test_resume_post_404_for_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post("/api/projects/nonexistent/experiments/exp-001/resume")
    assert r.status_code == 404


def test_resume_post_422_for_unknown_experiment(run_client):
    client, _, _ = run_client
    r = client.post("/api/projects/alpha/experiments/exp-bogus/resume")
    assert r.status_code == 422
