"""Tests for the dashboard's interactive builder wizard.

Covers two seams:

1. ``_DashboardBuilderShim`` — the ProjectBuilder-shaped adapter the
   dashboard hands to ``run_builder_loop``. It must persist research
   intent (refined question, preferences, hypotheses, co-drafted
   criteria) and the advisor suggestions exactly the way the CLI's
   real ``ProjectBuilder`` does. Pre-7.5 the shim only implemented
   ``set_initial_suggestions`` so the intent steps silently didn't
   persist on the dashboard surface.

2. The four wizard endpoints (``builder/start|stream|answer|abort``)
   driven end-to-end with a scripted agent runner through TestClient.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace


# ── 1. Shim persistence ────────────────────────────────────────────


@pytest.fixture
def scaffolded_project(tmp_path: Path, tmp_urika_home: Path) -> tuple[Path, Path]:
    """An on-disk workspace mirroring what POST /api/projects lays
    down before the wizard starts. Returns (projects_dir, project_dir)."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_dir = projects_dir / "alpha"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="alpha", question="Original?", mode="exploratory"),
    )
    return projects_dir, project_dir


def _project_block(project_dir: Path) -> dict:
    with open(project_dir / "urika.toml", "rb") as f:
        return tomllib.load(f)["project"]


class TestDashboardBuilderShim:
    def test_shim_persists_research_intent_like_cli_builder(
        self, scaffolded_project
    ) -> None:
        """All the loop-gathered intent setters must round-trip to the
        on-disk project via apply_research_intent — same as the CLI."""
        from urika.dashboard.routers.api import _DashboardBuilderShim

        projects_dir, project_dir = scaffolded_project
        shim = _DashboardBuilderShim(name="alpha", projects_dir=projects_dir)

        shim.set_refined_question("Which features predict choice?")
        shim.set_research_preferences("statistical", "interpretable")
        shim.set_hypotheses(["H1: velocity predicts choice"])
        shim.set_initial_criteria(
            {
                "type": "exploratory",
                "quality": {"min_approaches": 2},
                "completeness": ["establish baselines"],
                "user_amendments": "also require cross-validation",
            }
        )
        shim.set_initial_suggestions(
            {"suggestions": [{"name": "rf-baseline", "method": "random forest"}]}
        )
        shim.apply_research_intent()

        block = _project_block(project_dir)
        assert block["question"] == "Which features predict choice?"
        assert block["analysis_approach"] == "statistical"
        assert block["interpretability_level"] == "interpretable"
        assert block["hypotheses"] == ["H1: velocity predicts choice"]

        from urika.core.criteria import load_criteria

        latest = load_criteria(project_dir)
        assert latest.criteria["user_amendments"] == "also require cross-validation"

        suggestions_path = project_dir / "suggestions" / "initial.json"
        assert suggestions_path.exists()
        sdata = json.loads(suggestions_path.read_text(encoding="utf-8"))
        assert sdata["suggestions"][0]["name"] == "rf-baseline"

    def test_shim_without_refinement_keeps_existing_question(
        self, scaffolded_project
    ) -> None:
        """The shim starts with an empty question, so apply_research_intent
        must NOT clobber the question already in urika.toml unless the
        feasibility step actually refined it."""
        from urika.dashboard.routers.api import _DashboardBuilderShim

        projects_dir, project_dir = scaffolded_project
        shim = _DashboardBuilderShim(name="alpha", projects_dir=projects_dir)
        shim.apply_research_intent()
        assert _project_block(project_dir)["question"] == "Original?"

    def test_shim_has_every_setter_the_loop_pushes(self) -> None:
        """``run_builder_loop`` pushes intent via duck-typed setters; a
        missing one is a silent no-persist. Pin the full set."""
        from urika.dashboard.routers.api import _DashboardBuilderShim

        for method in (
            "set_initial_suggestions",
            "set_refined_question",
            "set_research_preferences",
            "set_hypotheses",
            "set_initial_criteria",
            "apply_research_intent",
        ):
            assert callable(getattr(_DashboardBuilderShim, method, None)), (
                f"_DashboardBuilderShim is missing {method}"
            )


# ── 2. Wizard endpoints (start / stream / answer / abort) ──────────


from fastapi.testclient import TestClient  # noqa: E402

from urika.agents.runner import AgentResult  # noqa: E402
from urika.dashboard.app import create_app  # noqa: E402

from .conftest import wait_until  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_builder_sessions():
    """Builder sessions are module-global; never leak between tests."""
    from urika.dashboard import builder_sessions

    builder_sessions._active.clear()
    yield
    builder_sessions._active.clear()


class _ScriptedRunner:
    """Role- and prompt-dispatched fake runner (mirrors the CLI
    builder-loop test pattern). Feasibility + hypothesis prompts get
    empty replies (best-effort steps skip silently); scoping signals
    ready immediately, so the loop's four fixed ``ask_user`` rounds
    (approach, interpretability, criteria, terminal choice) are the
    only questions."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        self.calls.append(config.name)
        text = ""
        if config.name == "project_builder":
            if (
                "Assess whether this research question" in prompt
                or "Propose 1-4 testable hypotheses" in prompt
            ):
                text = ""
            else:
                text = '```json\n{"ready": true}\n```'
        elif config.name == "advisor_agent":
            text = (
                '```json\n{"suggestions": [{"name": "rf-baseline", '
                '"method": "random forest"}]}\n```'
            )
        elif config.name == "planning_agent":
            text = (
                '```json\n{"method_name": "rf", "steps": ["fit"], '
                '"evaluation": {"strategy": "CV", "metrics": ["accuracy"]}}\n```'
            )
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s-{len(self.calls)}",
            num_turns=1,
            duration_ms=1,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0001,
        )


@pytest.fixture
def wizard_env(tmp_path: Path, monkeypatch):
    """A live dashboard (shared event loop via TestClient context
    manager) + a scaffolded project with real data, and the agent
    runner stubbed with the scripted fake."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    # TOML literal string — see test_api_create_project.py for rationale.
    (home / "settings.toml").write_text(
        f"projects_root = '{projects_root}'\n", encoding="utf-8"
    )
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    runner = _ScriptedRunner()
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: runner)

    app = create_app(project_root=tmp_path)
    with TestClient(app) as client:
        r = client.post(
            "/api/projects",
            data={
                "name": "wiz",
                "question": "Does a predict b?",
                "mode": "exploratory",
                "audience": "expert",
                "data_paths": str(csv),
            },
        )
        assert r.status_code == 201, r.text
        yield client, projects_root / "wiz", runner


def _session(name: str = "wiz"):
    from urika.dashboard import builder_sessions

    return builder_sessions.get_for_project(name)


def _await_question(prev_text: str | None) -> str:
    """Block until the loop parks a question different from the last
    one; return its text."""

    def _new_question_pending() -> bool:
        s = _session()
        q = s.pending_question_data if s else None
        return q is not None and q.text != prev_text

    wait_until(_new_question_pending, timeout=10, description="next builder question")
    return _session().pending_question_data.text


def _drive_to_completion(client: TestClient) -> list[str]:
    """Answer the loop's four fixed questions and wait for done.
    Returns the question texts seen, in order."""
    seen: list[str] = []
    answers = ["done", "done", "Accept", "Looks good — create the project"]
    prev: str | None = None
    for ans in answers:
        prev = _await_question(prev)
        seen.append(prev)
        r = client.post("/api/projects/wiz/builder/answer", json={"answer": ans})
        assert r.status_code == 200, r.text
    wait_until(lambda: _session().done, timeout=10, description="builder loop done")
    return seen


class TestBuilderEndpoints:
    def test_start_returns_session_id_and_409_while_active(self, wizard_env) -> None:
        client, _, _ = wizard_env
        r = client.post("/api/projects/wiz/builder/start")
        assert r.status_code == 202
        sid = r.json()["session_id"]
        assert sid

        # Second start while the first is in flight → 409.
        r2 = client.post("/api/projects/wiz/builder/start")
        assert r2.status_code == 409
        assert sid in r2.json()["detail"]

        # Cleanup: abort so no background task leaks past the test.
        client.post("/api/projects/wiz/builder/abort")

    def test_start_unknown_project_404(self, wizard_env) -> None:
        client, _, _ = wizard_env
        r = client.post("/api/projects/nope/builder/start")
        assert r.status_code == 404

    def test_answer_unblocks_full_loop_and_stream_carries_events(
        self, wizard_env
    ) -> None:
        """Drive the FULL loop through the endpoints: feasibility (skipped),
        scoping (ready), preferences, hypotheses (skipped), advisor,
        planning, criteria co-draft, terminal accept — then assert the
        SSE stream replays question/agent_text/done events and the
        on-disk artifacts match the CLI path."""
        client, project_dir, runner = wizard_env
        assert client.post("/api/projects/wiz/builder/start").status_code == 202

        seen = _drive_to_completion(client)
        assert seen[0] == "Analysis approach preference"
        assert seen[1] == "Model interpretability preference"
        assert "Proposed success criteria" in seen[2]
        assert seen[3] == "What would you like to do?"

        # All three agent roles ran.
        assert "advisor_agent" in runner.calls
        assert "planning_agent" in runner.calls
        assert runner.calls.count("project_builder") >= 1

        # Stream replays the queued events and terminates at done.
        r = client.get("/api/projects/wiz/builder/stream")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[len("data: ") :])
            for line in r.text.splitlines()
            if line.startswith("data: ")
        ]
        kinds = [e["kind"] for e in events]
        assert kinds.count("question") == 4
        assert "agent_text" in kinds
        assert kinds[-1] == "done"
        done = events[-1]
        assert done["payload"]["suggestions"]["suggestions"][0]["name"] == (
            "rf-baseline"
        )
        question_events = [e for e in events if e["kind"] == "question"]
        terminal = question_events[-1]
        assert terminal["payload"]["is_terminal_choice"] is True
        assert terminal["payload"]["options"] == [
            "Looks good — create the project",
            "Refine — I have suggestions",
            "Abort",
        ]

        # On-disk parity with the CLI path: suggestions flushed.
        sdata = json.loads(
            (project_dir / "suggestions" / "initial.json").read_text(encoding="utf-8")
        )
        assert sdata["suggestions"][0]["name"] == "rf-baseline"

    def test_stream_after_drained_done_session_emits_synthetic_done(
        self, wizard_env
    ) -> None:
        """Re-attaching to a finished session whose queue was already
        consumed (wizard page reload after completion) must close with
        a done event instead of heartbeating forever."""
        client, _, _ = wizard_env
        assert client.post("/api/projects/wiz/builder/start").status_code == 202
        _drive_to_completion(client)

        first = client.get("/api/projects/wiz/builder/stream")
        assert '"kind": "done"' in first.text

        second = client.get("/api/projects/wiz/builder/stream")
        assert second.status_code == 200
        events = [
            json.loads(line[len("data: ") :])
            for line in second.text.splitlines()
            if line.startswith("data: ")
        ]
        assert [e["kind"] for e in events] == ["done"]

    def test_answer_on_finished_session_409(self, wizard_env) -> None:
        client, _, _ = wizard_env
        assert client.post("/api/projects/wiz/builder/start").status_code == 202
        _drive_to_completion(client)
        r = client.post("/api/projects/wiz/builder/answer", json={"answer": "x"})
        assert r.status_code == 409

    def test_answer_with_no_pending_question_400(self, wizard_env) -> None:
        client, _, _ = wizard_env
        assert client.post("/api/projects/wiz/builder/start").status_code == 202
        # The loop is busy in its first agent call — no question parked
        # yet (the scripted runner is fast but the answer is posted
        # before we ever wait for a question; if a question IS already
        # pending, answering is legal, so only assert when none is).
        s = _session()
        if s.pending_question is None and not s.done:
            r = client.post("/api/projects/wiz/builder/answer", json={"answer": "x"})
            assert r.status_code == 400
        # Cleanup.
        client.post("/api/projects/wiz/builder/abort")

    def test_abort_terminates_session_and_trashes_project(
        self, wizard_env, tmp_path: Path
    ) -> None:
        client, project_dir, _ = wizard_env
        assert client.post("/api/projects/wiz/builder/start").status_code == 202
        _await_question(None)  # loop is parked on a question

        r = client.post("/api/projects/wiz/builder/abort")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["trash_path"], "partial project should be moved to trash"

        # Session is gone (subsequent calls 404) and the project is
        # unregistered + off its original path.
        assert _session() is None
        assert (
            client.post(
                "/api/projects/wiz/builder/answer", json={"answer": "x"}
            ).status_code
            == 404
        )
        assert client.get("/api/projects/wiz/builder/stream").status_code == 404
        assert client.post("/api/projects/wiz/builder/abort").status_code == 404
        assert not project_dir.exists()
        assert Path(body["trash_path"]).exists()

    def test_stream_and_answer_and_abort_404_without_session(self, wizard_env) -> None:
        client, _, _ = wizard_env
        assert client.get("/api/projects/wiz/builder/stream").status_code == 404
        assert (
            client.post(
                "/api/projects/wiz/builder/answer", json={"answer": "x"}
            ).status_code
            == 404
        )
        assert client.post("/api/projects/wiz/builder/abort").status_code == 404


class TestBuilderEndpointsAuth:
    def test_builder_endpoints_require_token_when_auth_enabled(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The wizard endpoints sit on the api router, which carries
        the router-level auth dependency — same posture as siblings."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("URIKA_HOME", str(home))
        (home / "projects.json").write_text("{}")

        app = create_app(project_root=tmp_path, auth_token="secret-token")
        client = TestClient(app)
        for method, url in (
            ("POST", "/api/projects/wiz/builder/start"),
            ("GET", "/api/projects/wiz/builder/stream"),
            ("POST", "/api/projects/wiz/builder/answer"),
            ("POST", "/api/projects/wiz/builder/abort"),
        ):
            r = client.request(method, url)
            assert r.status_code == 401, f"{method} {url} must require auth"
        # With the token, the same routes resolve past auth (404 — the
        # project/session doesn't exist, which proves auth was the gate).
        r = client.post(
            "/api/projects/wiz/builder/start",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert r.status_code == 404
