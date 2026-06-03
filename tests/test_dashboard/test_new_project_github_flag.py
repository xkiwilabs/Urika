"""Tests for ``--github`` / ``--public`` form fields on POST /api/projects.

The CLI's ``urika new --github / --no-github / --public`` flags map to
form-encoded fields on the dashboard's New Project modal. The fields:

  * ``github`` — "true" / "false" / unset; when unset falls back to
    ``[preferences] github_auto_create`` (default False).
  * ``public`` — "true" / "false"; defaults to private.

Behaviour mirrors :func:`urika.cli.project_new._maybe_create_github_repo`:
on failure (``gh`` missing, unauthed, etc.) the project is still created
and the response carries a structured ``github`` block describing what
went wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@dataclass
class _GhResult:
    ok: bool
    repo_url: str | None = None
    error: str | None = None
    install_hint: str | None = None


@pytest.fixture
def create_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    """Mirrors test_api_create_project.create_client."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    (home / "settings.toml").write_text(
        f"projects_root = '{projects_root}'\n", encoding="utf-8"
    )
    app = create_app(project_root=tmp_path, auth_token=None)
    return TestClient(app), projects_root


# ---------------------------------------------------------------------------
# New Project modal: form fields are present.
# ---------------------------------------------------------------------------


def test_new_project_modal_has_github_checkbox(create_client) -> None:
    client, _ = create_client
    body = client.get("/projects").text
    # The New Project form must carry a ``github`` field the server reads.
    assert 'name="github"' in body
    # And a ``public`` toggle.
    assert 'name="public"' in body
    # Helper note about gh CLI requirement.
    assert "gh" in body  # mentions the gh CLI somewhere in the modal


# ---------------------------------------------------------------------------
# POST handler: github=true triggers gh_create_repo.
# ---------------------------------------------------------------------------


def test_post_with_github_true_invokes_gh_create_repo(
    create_client, monkeypatch
) -> None:
    """Submitting ``github=true`` calls gh_create_repo with public=False
    by default."""
    client, projects_root = create_client

    calls: list[dict] = []

    def fake_gh(project_dir: Path, name: str, public: bool):
        calls.append({"project_dir": project_dir, "name": name, "public": public})
        return _GhResult(ok=True, repo_url=f"https://github.com/u/{name}")

    # Patch the function in the api module *and* the core module so the
    # router's import path is irrelevant.
    monkeypatch.setattr("urika.core.git.gh_create_repo", fake_gh)

    r = client.post(
        "/api/projects",
        data={
            "name": "gh-test",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "github": "true",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "gh-test"
    # The handler should report the github outcome in the response body.
    assert "github" in body
    assert body["github"]["ok"] is True
    assert body["github"]["repo_url"] == "https://github.com/u/gh-test"

    assert len(calls) == 1
    assert calls[0]["name"] == "gh-test"
    assert calls[0]["public"] is False


def test_post_with_github_and_public_sets_public(create_client, monkeypatch) -> None:
    """``public=true`` flips the visibility flag."""
    client, _ = create_client
    calls: list[dict] = []

    def fake_gh(project_dir: Path, name: str, public: bool):
        calls.append({"public": public})
        return _GhResult(ok=True, repo_url=None)

    monkeypatch.setattr("urika.core.git.gh_create_repo", fake_gh)

    r = client.post(
        "/api/projects",
        data={
            "name": "gh-pub",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "github": "true",
            "public": "true",
        },
    )
    assert r.status_code == 201, r.text
    assert calls[0]["public"] is True


def test_post_without_github_does_not_invoke_gh(create_client, monkeypatch) -> None:
    """The default (no ``github`` field, no preference) leaves the
    project as-is and does NOT shell out to ``gh``."""
    client, _ = create_client
    calls: list[dict] = []

    def fake_gh(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return _GhResult(ok=True)

    monkeypatch.setattr("urika.core.git.gh_create_repo", fake_gh)

    r = client.post(
        "/api/projects",
        data={
            "name": "no-gh",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
        },
    )
    assert r.status_code == 201
    assert calls == []


def test_post_with_github_failure_still_creates_project(
    create_client, monkeypatch
) -> None:
    """A ``gh`` failure must NOT bubble up — the project is still
    created and the response carries the failure details."""
    client, projects_root = create_client

    def fake_gh(project_dir: Path, name: str, public: bool):
        return _GhResult(
            ok=False,
            error="gh CLI not found",
            install_hint="brew install gh",
        )

    monkeypatch.setattr("urika.core.git.gh_create_repo", fake_gh)

    r = client.post(
        "/api/projects",
        data={
            "name": "gh-fail",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            "github": "true",
        },
    )
    assert r.status_code == 201, r.text
    # Project dir still on disk.
    assert (projects_root / "gh-fail").is_dir()
    body = r.json()
    assert body["github"]["ok"] is False
    assert body["github"]["error"] == "gh CLI not found"


def test_post_falls_back_to_preference_when_github_unset(
    create_client, monkeypatch
) -> None:
    """When the form omits ``github``, ``[preferences].github_auto_create``
    decides. Mirrors the CLI's resolution order."""
    client, _ = create_client

    calls: list[dict] = []

    def fake_gh(project_dir: Path, name: str, public: bool):
        calls.append({"name": name, "public": public})
        return _GhResult(ok=True, repo_url=None)

    monkeypatch.setattr("urika.core.git.gh_create_repo", fake_gh)

    # Set the preference to True in settings.toml.
    settings_path = Path(client.app.state.project_root) / "home" / "settings.toml"
    existing = settings_path.read_text(encoding="utf-8")
    settings_path.write_text(
        existing + "\n[preferences]\ngithub_auto_create = true\n",
        encoding="utf-8",
    )

    r = client.post(
        "/api/projects",
        data={
            "name": "auto-gh",
            "question": "Q?",
            "mode": "exploratory",
            "audience": "expert",
            # No ``github`` field.
        },
    )
    assert r.status_code == 201, r.text
    assert len(calls) == 1
    assert calls[0]["name"] == "auto-gh"
