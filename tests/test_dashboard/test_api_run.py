"""Tests for POST /api/projects/<name>/run.

Spawns are stubbed via monkeypatch so the tests never invoke a
real ``urika run`` subprocess. We assert: (a) the experiment dir
is materialized on disk, (b) the spawn helper was called with
the right args, and (c) JSON vs HTMX response shaping behaves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard import runs as runs_module
from urika.dashboard.app import create_app

# os.killpg / os.getpgid are POSIX-only — the Windows code path falls
# back to a bare os.kill (api.py: ``if hasattr(os, "killpg") ...``).
# These tests assert the POSIX branch was taken; pytest's monkeypatch
# can't ``setattr`` an attribute that doesn't exist on the target, so
# they fail at fixture time on Windows. The Windows fallback path is
# functionally distinct (no process group) and would need its own
# parametrization — out of scope for this Windows-CI cleanup.
_skip_on_windows_no_killpg = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX-only: os.killpg / os.getpgid don't exist on Windows.",
)


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


@_skip_on_windows_no_killpg
def test_run_stop_writes_flag_and_signals_process_group(run_client, monkeypatch):
    """Stop is graceful-then-forceful.

    1. ``"stop"`` is written to ``<project>/.urika/pause_requested`` so
       the orchestrator loop can call ``stop_session`` cleanly at the
       next turn boundary (writing the real ``stopped`` status).
    2. ``SIGTERM`` is sent to the **process group** (not just the
       leader PID) via ``os.killpg`` so children spawned with
       ``start_new_session=True`` (the SDK's ``claude`` CLI, any
       nested ``urika`` agents) also exit.

    Pre-v0.3.2 this endpoint sent a bare ``os.kill(pid, SIGTERM)`` to
    the leader only, and never wrote the flag — children outlived
    the parent and the dashboard card stayed on ``pending`` because
    the CLI had no SIGTERM handler to write ``stopped``.
    """
    import os
    import signal

    from urika.dashboard.routers import api as api_module

    client, _, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / ".lock").write_text(str(os.getpid()), encoding="utf-8")

    kill_calls: list[tuple[int, int]] = []
    killpg_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))

    def fake_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    monkeypatch.setattr(api_module.os, "kill", fake_kill)
    monkeypatch.setattr(api_module.os, "killpg", fake_killpg)
    monkeypatch.setattr(api_module.os, "getpgid", lambda pid: pid)

    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stop_signaled"
    assert body["pid"] == os.getpid()

    # SIGTERM goes to the process group, not the bare leader. The
    # liveness probe used to be ``os.kill(pid, 0)`` but now goes
    # through ``session._pid_is_alive`` (psutil-backed), so we no
    # longer assert on a probe call here.
    assert (os.getpid(), signal.SIGTERM) in killpg_calls
    assert (os.getpid(), signal.SIGTERM) not in kill_calls

    # Graceful-stop flag was written to the project's .urika dir.
    flag = proj / ".urika" / "pause_requested"
    assert flag.exists(), "pause_requested flag not written"
    assert flag.read_text(encoding="utf-8") == "stop"


def test_run_stop_returns_not_running_when_no_lock(run_client):
    """No .lock file → nothing is in flight, return not_running."""
    client, _, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    # Explicitly no .lock written.
    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    assert r.json() == {"status": "not_running"}


def test_run_stop_returns_not_running_when_pid_dead(run_client):
    """Lock file with a PID that doesn't exist → not_running.

    99999998 is far above any plausible live PID on a typical system.
    The endpoint probes with signal 0 first, gets ProcessLookupError,
    and returns the not_running status without attempting SIGTERM.
    """
    client, _, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / ".lock").write_text("99999998", encoding="utf-8")

    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    assert r.json() == {"status": "not_running"}


def test_run_stop_returns_not_running_when_lock_unreadable(run_client):
    """Lock file with non-integer content → treat as not running."""
    client, _, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / ".lock").write_text("not-a-pid", encoding="utf-8")

    r = client.post("/api/projects/alpha/runs/exp-001/stop")
    assert r.status_code == 200
    assert r.json() == {"status": "not_running"}


def test_run_stop_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post("/api/projects/nonexistent/runs/exp-001/stop")
    assert r.status_code == 404


def test_run_pause_writes_flag_file(run_client):
    """Pause writes "pause" to <project>/.urika/pause_requested. The
    orchestrator polls this file at each turn boundary."""
    client, _, proj = run_client
    r = client.post("/api/projects/alpha/runs/exp-001/pause")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pause_requested"
    assert body["experiment_id"] == "exp-001"
    flag_path = proj / ".urika" / "pause_requested"
    assert flag_path.exists()
    assert flag_path.read_text() == "pause"


def test_run_pause_creates_dotdir_if_missing(run_client):
    """The .urika dir doesn't exist by default; the endpoint must mkdir it."""
    client, _, proj = run_client
    assert not (proj / ".urika").exists()
    r = client.post("/api/projects/alpha/runs/exp-001/pause")
    assert r.status_code == 200
    assert (proj / ".urika").is_dir()


def test_run_pause_404_unknown_project(run_client):
    client, _, _ = run_client
    r = client.post("/api/projects/nonexistent/runs/exp-001/pause")
    assert r.status_code == 404


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


def test_run_post_forwards_advisor_first_flag(run_client):
    """The "Ask advisor first" checkbox in the modal POSTs
    ``advisor_first=on`` — the /run endpoint must thread that through
    to spawn_experiment_run as ``advisor_first=True`` so the spawned
    ``urika run`` subprocess receives ``--advisor-first`` and runs the
    advisor as the first step in the experiment loop."""
    client, spawn_calls, _ = run_client
    r = client.post(
        "/api/projects/alpha/run",
        headers={"accept": "application/json"},
        data={
            "audience": "expert",
            "max_turns": "5",
            "instructions": "",
            "advisor_first": "on",
        },
    )
    assert r.status_code == 200
    assert spawn_calls
    assert spawn_calls[0].get("advisor_first") is True


def test_run_post_advisor_first_default_false(run_client):
    """Without the checkbox in the form payload, advisor_first must
    default to False so the spawn helper omits ``--advisor-first``."""
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
    assert spawn_calls[0].get("advisor_first") is False


def test_run_post_creates_empty_experiment(run_client):
    """The dashboard's modal no longer asks for name/hypothesis. The
    /run endpoint always creates an empty experiment; either the
    advisor-first pre-loop step or the orchestrator's turn-1 name
    backfill fills them in once the run starts."""
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
    exp_id = body["experiment_id"]
    exp_json = json.loads(
        (proj / "experiments" / exp_id / "experiment.json").read_text()
    )
    assert exp_json["name"] == ""
    assert exp_json["hypothesis"] == ""


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


# ── Stop endpoints for non-run operations (v0.4 Track 1) ─────────────


def _setup_op_lock(tmp_path, lock_relpath: str, pid: int):
    """Write a lock file with the given PID at <project>/lock_relpath."""
    full = tmp_path / lock_relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(str(pid), encoding="utf-8")
    return full


def _patch_kill(monkeypatch, calls, killpg_calls):
    from urika.dashboard.routers import api as api_module

    monkeypatch.setattr(
        api_module.os, "kill", lambda pid, sig: calls.append((pid, sig))
    )
    monkeypatch.setattr(
        api_module.os,
        "killpg",
        lambda pgid, sig: killpg_calls.append((pgid, sig)),
    )
    monkeypatch.setattr(api_module.os, "getpgid", lambda pid: pid)


@pytest.mark.parametrize(
    "endpoint,lock_relpath",
    [
        ("/api/projects/alpha/advisor/stop", "projectbook/.advisor.lock"),
        ("/api/projects/alpha/finalize/stop", "projectbook/.finalize.lock"),
        ("/api/projects/alpha/summarize/stop", "projectbook/.summarize.lock"),
        ("/api/projects/alpha/build-tool/stop", "tools/.build.lock"),
    ],
)
@_skip_on_windows_no_killpg
def test_op_stop_signals_process_group(
    run_client, monkeypatch, endpoint, lock_relpath
):
    """Each non-run stop endpoint reads its lock file's PID and signals
    the process group via os.killpg, mirroring api_run_stop."""
    import os
    import signal

    client, _, proj = run_client
    _setup_op_lock(proj, lock_relpath, os.getpid())
    kill_calls: list[tuple[int, int]] = []
    killpg_calls: list[tuple[int, int]] = []
    _patch_kill(monkeypatch, kill_calls, killpg_calls)

    r = client.post(endpoint)
    assert r.status_code == 200
    assert r.json()["status"] == "stop_signaled"
    # Probe is now psutil-backed (see api_run_stop comment), so we
    # only assert the SIGTERM dispatch.
    assert (os.getpid(), signal.SIGTERM) in killpg_calls
    assert (os.getpid(), signal.SIGTERM) not in kill_calls


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/projects/alpha/advisor/stop",
        "/api/projects/alpha/finalize/stop",
        "/api/projects/alpha/summarize/stop",
        "/api/projects/alpha/build-tool/stop",
    ],
)
def test_op_stop_returns_not_running_when_no_lock(run_client, endpoint):
    """No lock file → not_running."""
    client, _, _proj = run_client
    r = client.post(endpoint)
    assert r.status_code == 200
    assert r.json() == {"status": "not_running"}


@_skip_on_windows_no_killpg
def test_present_stop_signals_process_group(run_client, monkeypatch):
    """Present is scoped to an experiment; lock lives in the exp dir."""
    import os
    import signal

    client, _, proj = run_client
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / ".present.lock").write_text(
        str(os.getpid()), encoding="utf-8"
    )
    kill_calls: list[tuple[int, int]] = []
    killpg_calls: list[tuple[int, int]] = []
    _patch_kill(monkeypatch, kill_calls, killpg_calls)

    r = client.post("/api/projects/alpha/runs/exp-001/present/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stop_signaled"
    assert (os.getpid(), signal.SIGTERM) in killpg_calls


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/projects/unknown/advisor/stop",
        "/api/projects/unknown/finalize/stop",
        "/api/projects/unknown/summarize/stop",
        "/api/projects/unknown/build-tool/stop",
        "/api/projects/unknown/runs/exp-001/present/stop",
    ],
)
def test_op_stop_404_unknown_project(run_client, endpoint):
    client, _, _proj = run_client
    r = client.post(endpoint)
    assert r.status_code == 404
