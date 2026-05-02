"""Tests for the orchestrator-sessions list page and delete endpoint."""

from urika.core.orchestrator_sessions import (
    OrchestratorSession,
    save_session,
)


def test_sessions_list_404_unknown_project(client_with_projects):
    r = client_with_projects.get("/projects/does-not-exist/sessions")
    assert r.status_code == 404


def test_sessions_list_empty_state(client_with_projects):
    r = client_with_projects.get("/projects/alpha/sessions")
    assert r.status_code == 200
    assert "No conversation sessions yet" in r.text


def test_sessions_empty_state_credits_orchestrator_chat_not_advisor(client_with_projects):
    """Sessions are saved from REPL/TUI orchestrator chat (and the
    advisor — both write `OrchestratorSession` entries to disk via
    different code paths). The empty-state copy must not mislead
    users into thinking that autonomous commands like `urika run`
    create sessions."""
    r = client_with_projects.get("/projects/alpha/sessions")
    assert r.status_code == 200
    body = r.text
    assert "orchestrator" in body.lower()
    # Old wrong claim must be gone
    assert "as you chat with the advisor" not in body


def test_sessions_empty_state_disambiguates_run_and_finalize(client_with_projects):
    """Regression (v0.4.1): users running `urika run` + `urika finalize`
    saw an empty Sessions tab and assumed it was broken. The
    empty-state copy must be explicit that those autonomous
    commands DON'T create sessions, and point at the three things
    that do."""
    r = client_with_projects.get("/projects/alpha/sessions")
    assert r.status_code == 200
    body = r.text
    # Explicit "not created by …" disambiguation
    assert "urika run" in body
    assert "urika finalize" in body
    # Three on-ramps
    assert "Advisor" in body
    assert "urika advisor alpha" in body
    assert "TUI" in body or "tui" in body.lower()
    # Cross-reference to the CLI surface
    assert "urika sessions list" in body


def test_sessions_list_renders_recent_sessions_with_previews(
    client_with_projects, tmp_path
):
    # ``client_with_projects`` fabricates the alpha project at
    # ``tmp_path / "alpha"`` (see conftest.py). Both fixtures share
    # the same ``tmp_path`` so we can resolve the project dir
    # directly.
    project_path = tmp_path / "alpha"
    s1 = OrchestratorSession(
        session_id="20260428-100000",
        started="2026-04-28T10:00:00Z",
        updated="2026-04-28T10:05:00Z",
        preview="What's the right model for tree count data?",
    )
    s2 = OrchestratorSession(
        session_id="20260428-110000",
        started="2026-04-28T11:00:00Z",
        updated="2026-04-28T11:30:00Z",
        preview="Try mixed-effects with random intercept",
    )
    save_session(project_path, s1)
    save_session(project_path, s2)

    r = client_with_projects.get("/projects/alpha/sessions")
    assert r.status_code == 200
    body = r.text
    assert "tree count data" in body
    assert "mixed-effects" in body
    # Newer session should appear first (descending by ID/timestamp).
    assert body.index("mixed-effects") < body.index("tree count data")


def test_session_delete_returns_204_and_removes_file(
    client_with_projects, tmp_path
):
    project_path = tmp_path / "alpha"
    s = OrchestratorSession(
        session_id="20260428-120000",
        started="2026-04-28T12:00:00Z",
        updated="2026-04-28T12:00:00Z",
    )
    save_session(project_path, s)

    r = client_with_projects.delete(
        "/api/projects/alpha/sessions/20260428-120000"
    )
    assert r.status_code == 204

    # File gone.
    assert not (
        project_path / ".urika" / "sessions" / "20260428-120000.json"
    ).exists()


def test_session_delete_404_unknown_session(client_with_projects):
    r = client_with_projects.delete(
        "/api/projects/alpha/sessions/does-not-exist"
    )
    assert r.status_code == 404


def test_session_delete_404_unknown_project(client_with_projects):
    r = client_with_projects.delete(
        "/api/projects/missing/sessions/whatever"
    )
    assert r.status_code == 404


def test_sessions_list_links_to_advisor_with_session_id(
    client_with_projects, tmp_path
):
    project_path = tmp_path / "alpha"
    s = OrchestratorSession(
        session_id="20260428-130000",
        started="2026-04-28T13:00:00Z",
        updated="2026-04-28T13:00:00Z",
        preview="hello",
    )
    save_session(project_path, s)

    r = client_with_projects.get("/projects/alpha/sessions")
    assert r.status_code == 200
    assert "/projects/alpha/advisor?session_id=20260428-130000" in r.text
