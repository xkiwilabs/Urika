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


def test_project_home_recent_experiments_has_new_and_see_all_buttons(
    client_with_experiments,
):
    """Above the recent-experiments list there must be a New
    experiment button (linking to ?new=1 so the modal auto-opens on
    arrival) and a See all link to the full experiments list."""
    body = client_with_experiments.get("/projects/alpha").text
    assert 'href="/projects/alpha/experiments?new=1"' in body
    assert "+ New experiment" in body
    assert 'href="/projects/alpha/experiments"' in body
    assert "See all" in body


def test_project_home_no_see_all_when_no_experiments(client_with_projects):
    """When the recent-experiments list is empty, See all hides — but
    the New experiment button stays so the user has a way to start one."""
    body = client_with_projects.get("/projects/alpha").text
    # alpha (in client_with_projects) has no experiments dirs.
    assert "See all" not in body
    assert "+ New experiment" in body


def test_project_home_sidebar_shows_project_links(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    # Sidebar has project-scoped Home/Experiments/Methods/Knowledge/Settings links.
    # Run + Criteria links were removed; Run is a button on /experiments and
    # Criteria is reachable from project settings.
    assert "/projects/alpha/experiments" in body
    assert "/projects/alpha/methods" in body
    assert "/projects/alpha/knowledge" in body
    assert "/projects/alpha/settings" in body


def test_experiments_page_returns_200_and_shows_experiments(client_with_experiments):
    r = client_with_experiments.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # All 7 experiments visible (this page shows the full list, not just top 5)
    for i in range(1, 8):
        assert f"exp-{i:03d}" in body


def test_experiments_page_renders_sort_dropdown(client_with_experiments):
    r = client_with_experiments.get("/projects/alpha/experiments")
    body = r.text
    assert 'class="list-sort"' in body
    assert "Newest first" in body
    assert "Oldest first" in body
    # Each row carries the data attribute the client-side sort reads.
    assert "data-last-touched" in body


def test_new_experiment_modal_has_advisor_first_checkbox(client_with_experiments):
    """The redesigned modal shows an "Ask advisor first" checkbox at the
    top of the new-experiment form. Default checked — the user opts
    out, not in. The checkbox posts ``advisor_first=on`` to /run, which
    threads it through to the CLI's --advisor-first flag."""
    r = client_with_experiments.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert "Ask advisor to suggest the next experiment" in body
    assert 'name="advisor_first"' in body
    # Default checked.
    assert 'type="checkbox" name="advisor_first" value="on" checked' in body


def test_new_experiment_modal_no_three_step_state_machine(client_with_experiments):
    """Regression guard: the old advisor-first implementation used a
    three-step Alpine state machine (compose / asking / review) with a
    separate /suggest-experiment endpoint. The simpler shape replaces
    that with a single checkbox + CLI flag passthrough — none of the
    old state markers must be present."""
    r = client_with_experiments.get("/projects/alpha/experiments")
    body = r.text
    assert "step === 'compose'" not in body
    assert "step === 'asking'" not in body
    assert "step === 'review'" not in body
    assert "suggest-experiment" not in body
    # The Review-step name/hypothesis inputs are gone.
    assert 'name="name"' not in body
    assert 'name="hypothesis"' not in body


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


def test_experiment_detail_shows_evaluate_button_and_modal(client_with_runs):
    """The Outputs section must contain an Evaluate button that opens
    the 'evaluate' modal, and the modal form must POST to the
    per-experiment evaluate API."""
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    # Button dispatches Alpine open-modal event with id=evaluate
    assert "open-modal" in body
    assert "id: 'evaluate'" in body
    assert ">Evaluate<" in body or "Evaluate\n" in body
    # Modal form posts to the per-experiment evaluate endpoint
    assert 'hx-post="/api/projects/alpha/experiments/exp-001/evaluate"' in body
    # Instructions textarea is present
    assert 'name="instructions"' in body


def test_experiment_detail_404_for_unknown_experiment(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-999")
    assert r.status_code == 404


def test_experiment_detail_404_for_unknown_project(client_with_runs):
    r = client_with_runs.get("/projects/nonexistent/experiments/exp-001")
    assert r.status_code == 404


def test_experiment_report_route_renders_labbook_narrative(tmp_path: Path, monkeypatch):
    """The "View report" route must render labbook/narrative.md when
    no report.md exists. The report agent writes narrative.md as part
    of the standard ``urika run`` flow; without this fallback the
    dashboard says "no report" after a successful run."""
    proj = _make_project_with_runs(tmp_path, "alpha", "exp-001", 1)
    labbook = proj / "experiments" / "exp-001" / "labbook"
    labbook.mkdir(parents=True, exist_ok=True)
    (labbook / "narrative.md").write_text(
        "# Findings narrative\n\nDetails here.\n", encoding="utf-8"
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    body = client.get("/projects/alpha/experiments/exp-001/report").text
    assert "Findings narrative" in body


def test_experiment_detail_shows_view_report_when_only_narrative_exists(
    tmp_path: Path, monkeypatch
):
    """has_report flag must accept either report.md OR
    labbook/narrative.md so the "View report" button surfaces after
    every successful run."""
    proj = _make_project_with_runs(tmp_path, "alpha", "exp-001", 1)
    labbook = proj / "experiments" / "exp-001" / "labbook"
    labbook.mkdir(parents=True, exist_ok=True)
    (labbook / "narrative.md").write_text("# x\n\nyz", encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    body = client.get("/projects/alpha/experiments/exp-001").text
    assert "View report" in body


def test_experiments_list_falls_back_to_experiment_id_when_name_empty(
    tmp_path: Path, monkeypatch
):
    """Empty experiment.name must NOT render as a blank title — fall
    back to the experiment_id so the row stays scannable. Covers the
    dashboard's pre-create-with-empty-name handoff before the
    orchestrator's first-turn name backfill kicks in."""
    proj = _make_project_with_experiments(tmp_path, "alpha", 1)
    exp_json = proj / "experiments" / "exp-001" / "experiment.json"
    exp_json.write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "",
                "hypothesis": "",
                "status": "completed",
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    body = client.get("/projects/alpha/experiments").text
    assert "Exp-001" in body or "exp-001" in body


def test_experiment_detail_shows_danger_zone(client_with_runs):
    """Type-name confirm + Move-to-trash button gated on the exp_id."""
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert "Danger zone" in body
    assert 'hx-delete="/api/projects/alpha/experiments/exp-001"' in body
    assert "typed !== 'exp-001'" in body
    # Trash dir explanation mentions the project-local trash path
    assert "trash" in body


def test_experiment_detail_danger_zone_disabled_when_locked(
    tmp_path: Path, monkeypatch
):
    """A live .lock under the experiment dir disables the Move-to-trash button."""
    import os

    proj = _make_project_with_runs(tmp_path, "alpha", "exp-001", 1)
    lock = proj / "experiments" / "exp-001" / ".lock"
    lock.write_text(str(os.getpid()))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert "Danger zone" in body
    # The blocking lock path is rendered for the user.
    assert str(lock) in body
    # The disabled button is rendered (no hx-delete on the disabled variant).
    assert "Move to trash" in body
    assert 'type="button" disabled' in body


def test_experiments_list_does_not_have_inline_delete_button(
    client_with_experiments,
):
    """Delete is NOT a row-level action — it lives only in the
    experiment-detail page's Danger zone (with type-name confirmation,
    appropriate friction for a destructive op). Per-row hx-confirm
    popups would compete with that and offer weaker friction.
    """
    body = client_with_experiments.get("/projects/alpha/experiments").text
    assert 'hx-delete="/api/projects/alpha/experiments/' not in body, (
        "row-level Delete button found; should only live in Danger zone"
    )


def test_experiments_list_status_says_running_when_lock_alive(
    tmp_path: Path, monkeypatch
):
    """A live <exp>/.lock means the agent is working RIGHT NOW. The
    row's status tag must reflect that even if progress.json hasn't
    been written yet (which is normal during the spawn-to-first-write
    window). Without this override, freshly-spawned experiments show
    "pending" while actively running."""
    import os

    proj = _make_project_with_experiments(tmp_path, "alpha", 1)
    # Drop a live PID lock on exp-001 to simulate a running experiment.
    (proj / "experiments" / "exp-001" / ".lock").write_text(str(os.getpid()))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    body = client.get("/projects/alpha/experiments").text
    # The exp-001 row's status pill must say "running", not "pending".
    assert "tag--running" in body
    # And NOT pending for that experiment (other rows might still
    # legitimately be pending — but exp-001 with a live lock isn't).
    assert ">running<" in body


def test_experiment_detail_status_says_running_when_lock_alive(
    tmp_path: Path, monkeypatch
):
    """Same override on the experiment detail page."""
    import os

    proj = _make_project_with_runs(tmp_path, "alpha", "exp-001", 0)
    (proj / "experiments" / "exp-001" / ".lock").write_text(str(os.getpid()))

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    body = client.get("/projects/alpha/experiments/exp-001").text
    assert "tag--running" in body


def test_experiments_list_card_layout_has_three_main_rows(
    client_with_experiments,
):
    """Experiment cards on the list page mirror the project-home
    "Recent experiments" cards: title, experiment_id, and a third
    muted line with run count + last-touched timestamp. Status tag
    sits alone in the meta column."""
    body = client_with_experiments.get("/projects/alpha/experiments").text
    assert "list-item-detail" in body
    # Three pieces of info on the first card.
    assert "exp-007" in body
    assert "0 runs" in body or "1 run" in body or "2 runs" in body


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


def test_knowledge_page_has_add_button_and_modal(client_with_projects):
    """Task 11E.3: knowledge page exposes a '+ Add knowledge' button and
    a modal form posting via HTMX to the API."""
    r = client_with_projects.get("/projects/alpha/knowledge")
    assert r.status_code == 200
    body = r.text
    assert "+ Add knowledge" in body
    assert "modal-backdrop" in body
    assert 'hx-post="/api/projects/alpha/knowledge"' in body
    assert 'name="source"' in body


def _make_project_minimal(root: Path, name: str) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q"\nmode = "exploratory"\n'
        f'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    return proj


@pytest.fixture
def client_run_log(tmp_path: Path, monkeypatch) -> TestClient:
    """Minimal client used by the live-log-page tests below.

    The old client_run_no_active / client_run_active fixtures distinguished
    between "no run is in flight" vs "a run is in flight" — relevant only
    for the now-deleted /run page that toggled between a form and a
    'view live log' link. The /log page itself doesn't care, so a single
    minimal fixture is all the remaining tests need.
    """
    _make_project_minimal(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_run_page_redirects_to_experiments_with_new_flag(client_with_projects):
    """The standalone /run page is gone; the URL now redirects to the
    experiments list with ``?new=1`` so Alpine auto-opens the modal."""
    r = client_with_projects.get("/projects/alpha/run", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/projects/alpha/experiments?new=1"


def test_run_page_redirect_404_unknown_project(client_with_projects):
    """The redirect is purely a URL rewrite — it doesn't validate the
    project name. Following the redirect lands on the experiments page
    which does the 404."""
    r = client_with_projects.get("/projects/nonexistent/run", follow_redirects=True)
    assert r.status_code == 404


def test_experiments_page_includes_new_experiment_modal(client_with_projects):
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert "+ New experiment" in body
    assert "modal-backdrop" in body
    assert 'name="audience"' in body
    assert 'name="max_turns"' in body
    assert 'name="instructions"' in body
    assert 'hx-post="/api/projects/alpha/run"' in body


def test_experiments_page_modal_includes_audience_options(
    client_with_projects,
):
    """The modal needs valid_audiences from the route."""
    r = client_with_projects.get("/projects/alpha/experiments")
    body = r.text
    # The fixture sets audience=expert; it must show up as an
    # <option> value in the dropdown.
    assert 'value="expert"' in body


def test_new_experiment_modal_has_no_name_or_hypothesis_field(
    client_with_projects,
):
    """The redesigned modal mirrors ``urika run`` exactly: no name, no
    hypothesis, no mode. Either the advisor-first pre-loop step (when
    the checkbox is on) or the orchestrator's turn-1 backfill (when
    it's off) fills both fields once the run actually starts."""
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert 'id="ne-name"' not in body
    assert 'id="ne-hypothesis"' not in body
    assert 'name="name"' not in body
    assert 'name="hypothesis"' not in body


def test_new_experiment_modal_has_no_mode_field(client_with_projects):
    """Mode is project-level, not per-experiment; remove it from the form."""
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert 'id="ne-mode"' not in body
    assert 'name="mode"' not in body


def test_new_experiment_modal_pre_selects_project_audience(tmp_path: Path, monkeypatch):
    """The Audience dropdown must pre-select the project's configured
    audience — same pattern as project_home.html."""
    from fastapi.testclient import TestClient

    from urika.dashboard.app import create_app

    proj = tmp_path / "alpha"
    proj.mkdir()
    # audience = "expert"
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # The "expert" option must be selected; "novice" / "standard" must not.
    assert 'value="expert" selected' in body
    assert 'value="novice" selected' not in body
    assert 'value="standard" selected' not in body


def test_new_experiment_modal_instructions_label_says_optional(
    client_with_projects,
):
    """Label must literally read ``Instructions (optional)`` so the
    optionality is visible without reading the placeholder."""
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    assert "Instructions (optional)" in r.text


def test_new_experiment_modal_shows_all_options_inline(
    client_with_projects,
):
    """All run flags are surfaced inline — no Advanced collapsible.
    Users hit these every run; hiding them behind a toggle just adds
    a click. ``auto_limit`` lets the user pick capped vs unlimited
    autonomous mode. ``resume`` is NOT in this modal — it's a
    per-experiment action exposed on the experiments list."""
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    # No Advanced toggle button.
    assert "showAdvanced" not in body
    # All run-flag fields render inline.
    assert 'name="max_turns"' in body
    assert 'name="auto"' in body
    assert 'name="max_experiments"' in body
    assert 'name="auto_limit"' in body
    assert 'name="review_criteria"' in body
    # Resume is per-experiment now, NOT a new-experiment option.
    assert 'name="resume"' not in body


def test_new_experiment_modal_audience_above_instructions(client_with_projects):
    """Audience select must render BEFORE the instructions textarea —
    instructions is the open-ended attention-heavy field that belongs
    last. Pin the order so a future template tweak can't regress it."""
    body = client_with_projects.get("/projects/alpha/experiments").text
    audience_pos = body.find('id="ne-audience"')
    instructions_pos = body.find('id="ne-instructions"')
    assert audience_pos != -1 and instructions_pos != -1
    assert audience_pos < instructions_pos, (
        f"audience ({audience_pos}) must appear before instructions "
        f"({instructions_pos})"
    )


def test_run_log_page_returns_200_and_has_eventsource(client_run_log):
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    body = r.text
    assert "EventSource" in body
    # SSE URL embedded in the inline script
    assert "/api/projects/alpha/runs/exp-001/stream" in body
    # Pre element to receive log lines
    assert 'id="log"' in body


def test_run_log_page_404_unknown_project(client_run_log):
    r = client_run_log.get("/projects/nonexistent/experiments/exp-001/log")
    assert r.status_code == 404


def test_run_log_page_works_without_existing_experiment(client_run_log):
    """Loading the log page right after a POST /api/projects/.../run is
    valid even before the experiment dir has any output."""
    r = client_run_log.get("/projects/alpha/experiments/exp-future/log")
    # Project exists; the page itself doesn't validate the experiment id —
    # SSE handles the no-data case.
    assert r.status_code == 200


def test_run_log_page_type_evaluate_carries_query_in_sse_url(client_run_log):
    """When the page is loaded with ?type=evaluate the embedded
    EventSource URL must point at the evaluate log stream so the
    browser tails evaluate.log instead of run.log."""
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log?type=evaluate")
    assert r.status_code == 200
    body = r.text
    assert "/api/projects/alpha/runs/exp-001/stream?type=evaluate" in body
    # Heading should reflect the agent type
    assert "evaluate" in body
    # The Pause/Stop run buttons are run-only — hidden for
    # evaluate/report/present
    assert 'id="stop-btn"' not in body
    assert 'id="pause-btn"' not in body


def test_run_log_page_type_report_carries_query_in_sse_url(client_run_log):
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log?type=report")
    assert r.status_code == 200
    assert "/api/projects/alpha/runs/exp-001/stream?type=report" in r.text
    assert 'id="stop-btn"' not in r.text
    assert 'id="pause-btn"' not in r.text


def test_run_log_page_type_present_carries_query_in_sse_url(client_run_log):
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log?type=present")
    assert r.status_code == 200
    assert "/api/projects/alpha/runs/exp-001/stream?type=present" in r.text
    assert 'id="stop-btn"' not in r.text
    assert 'id="pause-btn"' not in r.text


def test_run_log_has_both_pause_and_stop_buttons(client_run_log):
    """The default run log page must surface both Pause (graceful) and
    Stop (immediate kill) buttons. Pause is btn--secondary; Stop is
    btn--danger so it reads visually red."""
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    body = r.text
    assert 'id="pause-btn"' in body
    assert 'id="stop-btn"' in body
    # Stop fires the kill endpoint; Pause fires the flag-write endpoint.
    assert "/api/projects/alpha/runs/exp-001/stop" in body
    assert "/api/projects/alpha/runs/exp-001/pause" in body
    # Stop is the destructive action — class must include btn--danger.
    assert "btn--danger" in body


def test_run_log_pause_button_only_on_run_type(client_run_log):
    """The pause button is run-only — same gating as the stop button.
    Verified in test_run_log_page_type_*_carries_query_in_sse_url above
    for evaluate/report/present; this test pins the contract directly."""
    for log_type in ("evaluate", "report", "present"):
        r = client_run_log.get(
            f"/projects/alpha/experiments/exp-001/log?type={log_type}"
        )
        assert r.status_code == 200
        assert 'id="pause-btn"' not in r.text, (
            f"pause-btn must not appear for type={log_type}"
        )


def test_run_log_presentation_link_opens_in_new_tab(client_run_log):
    """Presentation links must always open in a new tab — reveal.js takes
    over the whole window, and losing the dashboard tab to a deck would
    be a navigation trap. Pin every presentation <a> to carry
    ``target="_blank" rel="noopener"`` consistently."""
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log")
    assert r.status_code == 200
    body = r.text
    # Find the presentation link and assert the attrs sit on the same tag.
    import re

    match = re.search(
        r'<a[^>]*id="link-presentation"[^>]*>',
        body,
        re.DOTALL,
    )
    assert match, "presentation link not found on run log page"
    tag = match.group(0)
    assert 'target="_blank"' in tag, f"presentation link missing target=_blank: {tag!r}"
    assert 'rel="noopener"' in tag, f"presentation link missing rel=noopener: {tag!r}"


def test_run_log_page_type_unknown_falls_back_to_run(client_run_log):
    """An unknown ?type value silently degrades to run — the page still
    renders, the SSE URL has no query string, and both Pause and Stop
    buttons are back."""
    r = client_run_log.get("/projects/alpha/experiments/exp-001/log?type=bogus")
    assert r.status_code == 200
    body = r.text
    # No ?type= in the SSE URL when defaulting to run
    assert '/api/projects/alpha/runs/exp-001/stream"' in body
    assert "?type=" not in body.split("EventSource")[1].split(";")[0]
    assert 'id="stop-btn"' in body
    assert 'id="pause-btn"' in body


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
    assert 'src="/projects/alpha/experiments/exp-001/artifacts/fig.png"' in body
    # The unrewritten relative forms should NOT be in the page.
    assert 'src="fig.png"' not in body
    assert 'src="artifacts/fig.png"' not in body


def test_report_view_leaves_absolute_urls_alone(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    exp_dir = proj / "experiments" / "exp-001"
    (exp_dir / "report.md").write_text(
        "[Link](https://example.com/page)\n\n![Remote](https://example.com/x.png)\n"
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


def test_experiment_presentation_injects_base_tag(client_with_runs):
    """The bare ``/presentation`` URL needs a <base> so relative
    ``reveal.css`` / ``reveal.min.js`` resolve under the
    sub-path route instead of the parent path."""
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "experiments" / "exp-001" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>x</title></head><body>deck</body></html>"
    )
    r = client_with_runs.get("/projects/alpha/experiments/exp-001/presentation")
    assert r.status_code == 200
    assert '<base href="/projects/alpha/experiments/exp-001/presentation/"' in r.text
    assert "deck" in r.text


def test_projectbook_presentation_injects_base_tag(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    pres_dir = proj / "projectbook" / "presentation"
    pres_dir.mkdir(parents=True, exist_ok=True)
    (pres_dir / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>x</title></head><body>final</body></html>"
    )
    r = client_with_runs.get("/projects/alpha/projectbook/presentation")
    assert r.status_code == 200
    assert '<base href="/projects/alpha/projectbook/presentation/"' in r.text
    assert "final" in r.text


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
    assert "tag tag--pending" not in body


def test_experiment_detail_uses_progress_status_when_present(client_with_pending_exp):
    r = client_with_pending_exp.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert "completed" in body
    assert "tag tag--pending" not in body


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


# --- Task 11E.2: Finalize button on project home + finalize log page ---


def test_project_home_has_finalize_button(client_with_projects):
    """Project home should expose a 'Finalize project' button that POSTs
    to the existing /api/.../finalize endpoint."""
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert "Finalize project" in body
    assert 'hx-post="/api/projects/alpha/finalize"' in body


def test_project_home_shows_full_multi_line_question(client_with_runs):
    """A multi-line research question should render in full — not be
    clamped to a single visual line. Newlines must survive (the
    container uses white-space: pre-wrap)."""
    proj = client_with_runs.app.state.project_root / "alpha"
    long_q = "Line one of the question.\nLine two with more details.\nLine three."
    # Rewrite urika.toml directly with a multi-line question.
    toml_path = proj / "urika.toml"
    toml_path.write_text(
        "[project]\n"
        f'name = "alpha"\n'
        f'question = "{long_q.replace(chr(10), "\\n")}"\n'
        'mode = "exploratory"\n'
        'description = ""\n'
        "\n"
        "[preferences]\n"
        'audience = "expert"\n'
    )
    r = client_with_runs.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert "Line one of the question." in body
    assert "Line two with more details." in body
    assert "Line three." in body
    # The container that holds the question must preserve newlines —
    # the .project-question class is the marker the CSS targets.
    assert "project-question" in body


def test_finalize_button_says_re_finalize_when_artifacts_exist(client_with_runs):
    """When report.md AND a presentation exist in projectbook/, the
    Finalize button label flips to 'Re-finalize project' so users
    know it will overwrite the existing artifacts."""
    proj = client_with_runs.app.state.project_root / "alpha"
    book = proj / "projectbook"
    book.mkdir(parents=True, exist_ok=True)
    (book / "report.md").write_text("done")
    (book / "presentation.html").write_text("<html></html>")
    r = client_with_runs.get("/projects/alpha")
    assert r.status_code == 200
    assert "Re-finalize project" in r.text


def test_finalize_button_says_finalize_when_no_artifacts(client_with_runs):
    r = client_with_runs.get("/projects/alpha")
    assert r.status_code == 200
    assert "Finalize project" in r.text
    assert "Re-finalize project" not in r.text


def test_finalize_log_page_returns_200_and_has_eventsource(client_with_projects):
    r = client_with_projects.get("/projects/alpha/finalize/log")
    assert r.status_code == 200
    body = r.text
    assert "EventSource" in body
    # SSE URL embedded in inline script
    assert "/api/projects/alpha/finalize/stream" in body
    # Pre element to receive log lines
    assert 'id="log"' in body


def test_finalize_log_page_404_unknown_project(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/finalize/log")
    assert r.status_code == 404


def test_finalize_log_page_breadcrumb(client_with_projects):
    r = client_with_projects.get("/projects/alpha/finalize/log")
    body = r.text
    # Breadcrumb chain: Projects / <project> / Finalize log
    assert "Finalize log" in body
    assert "/projects/alpha" in body
    # Back-to-project-home link surfaces on completion
    assert "Back to project home" in body


# ── Summarize button + log + summary view ─────────────────────────────────


def test_project_home_summarize_button_when_no_summary(client_with_projects):
    """No projectbook/summary.md → button reads "Summarize project"."""
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert "Summarize project" in body
    assert "Re-summarize project" not in body
    # Modal posts to the new endpoint
    assert "/api/projects/alpha/summarize" in body


def test_project_home_resummarize_button_when_summary_present(tmp_path, monkeypatch):
    """A pre-existing projectbook/summary.md flips the button label."""
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    book = proj / "projectbook"
    book.mkdir()
    (book / "summary.md").write_text("# Prior summary\n\nhello\n")

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert "Re-summarize project" in body
    # The Summary card surfaces in the final-outputs grid.
    assert "/projects/alpha/projectbook/summary" in body


def test_summarize_log_page_returns_200_and_has_eventsource(client_with_projects):
    r = client_with_projects.get("/projects/alpha/summarize/log")
    assert r.status_code == 200
    body = r.text
    assert "EventSource" in body
    assert "/api/projects/alpha/summarize/stream" in body
    assert 'id="log"' in body


def test_summarize_log_page_404_unknown_project(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/summarize/log")
    assert r.status_code == 404


def test_projectbook_summary_view_renders_when_present(tmp_path, monkeypatch):
    """GET /projects/<n>/projectbook/summary renders summary.md as HTML."""
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )
    book = proj / "projectbook"
    book.mkdir()
    (book / "summary.md").write_text(
        "# Project status\n\nThree experiments completed.\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

    app = create_app(project_root=tmp_path)
    client = TestClient(app)
    r = client.get("/projects/alpha/projectbook/summary")
    assert r.status_code == 200
    body = r.text
    assert "Project summary" in body  # title_override
    assert "Project status" in body
    assert "Three experiments completed" in body


def test_projectbook_summary_view_404_when_absent(client_with_projects):
    """When summary.md doesn't exist, the page returns 404."""
    r = client_with_projects.get("/projects/alpha/projectbook/summary")
    assert r.status_code == 404


def test_projectbook_summary_view_404_unknown_project(client_with_projects):
    r = client_with_projects.get("/projects/nonexistent/projectbook/summary")
    assert r.status_code == 404


# ── Phase B3: buttons reflect running state ──────────────────────────────
#
# Each trigger button on a project page should render either:
#   - idle: a <button> that opens the existing modal (no behavioural change)
#   - running: an <a class="btn--running" href="<log_url>"> with a pulsing dot
# Detection runs through ``urika.dashboard.active_ops.list_active_operations``,
# which keys off live PID lock files. Tests use ``os.getpid()`` so the lock
# resolves to a live process — matching the pattern in test_active_ops.py.


import os  # noqa: E402  — grouped near the Phase B3 tests for locality


def _drop_lock(path: Path) -> None:
    """Write a live-PID lock file at ``path`` (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


# ---- Summarize button on project_home ----------------------------------


def test_project_home_summarize_button_idle_opens_modal(client_with_projects):
    """No live summarize lock → button is the idle modal-opener."""
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # Idle: dispatches the open-modal event for the summarize modal.
    assert "id: 'summarize'" in body
    # Running affordance must NOT be present.
    assert "Summarize running" not in body
    assert "btn--running" not in body


def test_project_home_summarize_button_running_links_to_log(
    client_with_projects, tmp_path
):
    """Live ``projectbook/.summarize.lock`` → button becomes a link to
    the log page."""
    proj = tmp_path / "alpha"
    _drop_lock(proj / "projectbook" / ".summarize.lock")
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    # The running link target points at the live-tail log page.
    assert 'href="/projects/alpha/summarize/log"' in body
    assert "Summarize running" in body
    assert "btn--running" in body
    # The modal-open dispatch for summarize must NOT remain — the running
    # affordance replaces the button. (Other modals on the page still
    # exist, so we can't assert "open-modal" is absent globally; we just
    # check the summarize-id one is gone.)
    assert "id: 'summarize'" not in body


# ---- Finalize button on project_home ----------------------------------


def test_project_home_finalize_button_idle_opens_modal(client_with_projects):
    r = client_with_projects.get("/projects/alpha")
    body = r.text
    assert "id: 'finalize'" in body
    assert "Finalize running" not in body


def test_project_home_finalize_button_running_links_to_log(
    client_with_projects, tmp_path
):
    proj = tmp_path / "alpha"
    _drop_lock(proj / "projectbook" / ".finalize.lock")
    r = client_with_projects.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert 'href="/projects/alpha/finalize/log"' in body
    assert "Finalize running" in body
    assert "btn--running" in body
    assert "id: 'finalize'" not in body


# ---- Evaluate button on experiment_detail -----------------------------


def test_experiment_detail_evaluate_button_idle_opens_modal(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "id: 'evaluate'" in body
    assert "Evaluate running" not in body


def test_experiment_detail_evaluate_button_running_links_to_log(
    client_with_runs,
):
    proj = client_with_runs.app.state.project_root / "alpha"
    _drop_lock(proj / "experiments" / "exp-001" / ".evaluate.lock")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    assert r.status_code == 200
    body = r.text
    assert 'href="/projects/alpha/experiments/exp-001/log?type=evaluate"' in body
    assert "Evaluate running" in body
    assert "btn--running" in body
    assert "id: 'evaluate'" not in body


def test_experiment_detail_evaluate_lock_on_other_exp_does_not_affect_this(
    client_with_runs,
):
    """A live evaluate lock on a DIFFERENT experiment must NOT change
    this experiment's button — locks are scoped per-experiment-id."""
    proj = client_with_runs.app.state.project_root / "alpha"
    _drop_lock(proj / "experiments" / "exp-other" / ".evaluate.lock")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    # The live lock is on exp-other — exp-001 should still be idle.
    assert "id: 'evaluate'" in body
    assert "Evaluate running" not in body


# ---- Report button on experiment_detail -------------------------------


def test_experiment_detail_report_button_idle_opens_modal(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "id: 'report'" in body
    assert "report running" not in body.lower() or "report running…" not in body


def test_experiment_detail_report_button_running_links_to_log(client_with_runs):
    proj = client_with_runs.app.state.project_root / "alpha"
    _drop_lock(proj / "experiments" / "exp-001" / ".report.lock")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert 'href="/projects/alpha/experiments/exp-001/log?type=report"' in body
    assert "Report running" in body
    assert "btn--running" in body
    assert "id: 'report'" not in body


def test_experiment_detail_report_lock_on_other_exp_does_not_affect_this(
    client_with_runs,
):
    proj = client_with_runs.app.state.project_root / "alpha"
    _drop_lock(proj / "experiments" / "exp-other" / ".report.lock")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "id: 'report'" in body
    assert "Report running" not in body


# ---- Presentation button on experiment_detail -------------------------


def test_experiment_detail_present_button_idle_opens_modal(client_with_runs):
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "id: 'present'" in body
    assert "Presentation running" not in body


def test_experiment_detail_present_button_running_links_to_log(
    client_with_runs,
):
    proj = client_with_runs.app.state.project_root / "alpha"
    _drop_lock(proj / "experiments" / "exp-001" / ".present.lock")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert 'href="/projects/alpha/experiments/exp-001/log?type=present"' in body
    assert "Presentation running" in body
    assert "btn--running" in body
    assert "id: 'present'" not in body


def test_experiment_detail_present_lock_on_other_exp_does_not_affect_this(
    client_with_runs,
):
    proj = client_with_runs.app.state.project_root / "alpha"
    _drop_lock(proj / "experiments" / "exp-other" / ".present.lock")
    r = client_with_runs.get("/projects/alpha/experiments/exp-001")
    body = r.text
    assert "id: 'present'" in body
    assert "Presentation running" not in body


# ---- + New experiment button on experiments.html ----------------------


def test_experiments_page_new_experiment_button_idle_opens_modal(
    client_with_projects,
):
    r = client_with_projects.get("/projects/alpha/experiments")
    body = r.text
    assert "id: 'new-experiment'" in body
    assert "Experiment running" not in body
    assert "btn--running" not in body


def test_experiments_page_new_experiment_button_running_links_to_log(
    client_with_projects, tmp_path
):
    """Any live experiment ``.lock`` blocks a fresh run (the run op type
    is project-scoped per Phase B2). The + New experiment button should
    link to that running experiment's log."""
    proj = tmp_path / "alpha"
    _drop_lock(proj / "experiments" / "exp-running" / ".lock")
    r = client_with_projects.get("/projects/alpha/experiments")
    assert r.status_code == 200
    body = r.text
    assert 'href="/projects/alpha/experiments/exp-running/log"' in body
    assert "Experiment running" in body
    assert "btn--running" in body
    # The new-experiment modal-open dispatch must be gone.
    assert "id: 'new-experiment'" not in body


# ── Phase B5.2: completion CTAs on project-level log pages ────────────────


def test_summarize_log_has_view_summary_cta(client_with_projects):
    """The summarize log page must wire a hidden "View summary" button
    that JS reveals once the artifact probe confirms summary.md exists."""
    r = client_with_projects.get("/projects/alpha/summarize/log")
    assert r.status_code == 200
    body = r.text
    assert 'id="link-summary"' in body
    assert 'href="/projects/alpha/projectbook/summary"' in body
    # And the existing "Back to project home" link stays.
    assert "Back to project home" in body


def test_finalize_log_has_three_artifact_ctas(client_with_projects):
    """The finalize log page must wire hidden CTAs for all three
    finalize artifacts (report, presentation, findings)."""
    r = client_with_projects.get("/projects/alpha/finalize/log")
    assert r.status_code == 200
    body = r.text
    assert 'id="link-report"' in body
    assert 'href="/projects/alpha/projectbook/report"' in body
    assert 'id="link-presentation"' in body
    assert 'href="/projects/alpha/projectbook/presentation"' in body
    # The presentation CTA opens in a new tab.
    assert 'target="_blank"' in body
    assert 'id="link-findings"' in body
    assert 'href="/projects/alpha/findings"' in body


def test_summarize_log_calls_artifacts_probe_on_completion(client_with_projects):
    r = client_with_projects.get("/projects/alpha/summarize/log")
    assert r.status_code == 200
    assert 'fetch("/api/projects/alpha/artifacts/projectbook")' in r.text


def test_finalize_log_calls_artifacts_probe_on_completion(client_with_projects):
    r = client_with_projects.get("/projects/alpha/finalize/log")
    assert r.status_code == 200
    assert 'fetch("/api/projects/alpha/artifacts/projectbook")' in r.text
