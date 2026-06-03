"""REPL ``/github init|push|pull|status`` parity (v0.7 cross-surface sweep).

Pre-v0.7 the REPL/TUI had no surface for the v0.6 GitHub auto-backup
commands — users had to drop to a shell to run ``urika github push``.
The slash group dispatches to the same Click commands the CLI exposes,
so the logic stays single-sourced and the tests can lean on the
existing CLI test helpers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import click

from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace
from urika.repl.commands import cmd_github
from urika.repl.session import ReplSession


def _setup(tmp_path: Path, monkeypatch) -> ReplSession:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="proj", question="q", mode="exploratory", data_paths=[]),
    )
    ProjectRegistry().register("proj", project_dir)
    session = ReplSession()
    session.load_project(path=project_dir, name="proj")
    return session


def _make_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    return remote


def test_cmd_github_registered_as_project_command() -> None:
    """The slash must require a loaded project (operates on
    ``session.project_path``) and live in ``PROJECT_COMMANDS``."""
    from urika.repl.commands import PROJECT_COMMANDS

    assert "github" in PROJECT_COMMANDS
    assert PROJECT_COMMANDS["github"]["func"] is cmd_github


def test_status_after_init_shows_branch_and_remote(
    tmp_path, monkeypatch, capsys
) -> None:
    """``/github status`` mirrors ``urika github status``."""
    session = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)

    # Bootstrap via /github init --remote
    cmd_github(session, f"init --remote {remote}")
    capsys.readouterr()  # drain

    cmd_github(session, "status")
    out = capsys.readouterr().out
    assert "branch:" in out
    assert "remote:" in out
    assert str(remote) in out


def test_status_is_default_subcommand(tmp_path, monkeypatch, capsys) -> None:
    """Bare ``/github`` (no args) defaults to status (yellow-warning
    branch when no repo exists)."""
    session = _setup(tmp_path, monkeypatch)
    cmd_github(session, "")
    out = capsys.readouterr().out
    assert "not a git repo" in out


def test_init_creates_repo(tmp_path, monkeypatch, capsys) -> None:
    """``/github init`` writes .git/ + .gitignore + initial commit."""
    session = _setup(tmp_path, monkeypatch)
    cmd_github(session, "init")
    out = capsys.readouterr().out

    assert (session.project_path / ".git").is_dir()
    assert (session.project_path / ".gitignore").exists()
    assert "initial commit" in out.lower() or "initialised" in out.lower()


def test_init_with_remote_sets_origin(tmp_path, monkeypatch) -> None:
    session = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)

    cmd_github(session, f"init --remote {remote}")

    url = subprocess.run(
        ["git", "-C", str(session.project_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert url == str(remote)


def test_init_create_invokes_gh_helper(tmp_path, monkeypatch, capsys) -> None:
    """``/github init --create`` shells out to ``gh_create_repo`` (private
    by default), with ``--public`` flipping ``public=True``."""
    session = _setup(tmp_path, monkeypatch)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="https://github.com/u/proj"),
    ) as spy:
        cmd_github(session, "init --create")
    assert spy.called
    assert spy.call_args.kwargs.get("public") is False

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="https://github.com/u/proj"),
    ) as spy2:
        cmd_github(session, "init --create --public")
    assert spy2.call_args.kwargs.get("public") is True


def test_init_create_failure_does_not_kill_repl(tmp_path, monkeypatch) -> None:
    """``--create`` failure raises SystemExit(2) in the CLI; the REPL
    handler must swallow it so the REPL stays alive."""
    session = _setup(tmp_path, monkeypatch)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(
            ok=False, error="gh not found", install_hint="brew install gh"
        ),
    ):
        # Must not raise
        cmd_github(session, "init --create")


def test_push_clean_tree(tmp_path, monkeypatch, capsys) -> None:
    """``/github push`` succeeds against a local bare remote."""
    session = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    cmd_github(session, f"init --remote {remote}")
    capsys.readouterr()

    cmd_github(session, "push")
    out = capsys.readouterr().out
    assert "pushed" in out.lower()


def test_push_failure_does_not_kill_repl(tmp_path, monkeypatch) -> None:
    """Push without a remote raises SystemExit(1) in the CLI — the REPL
    must swallow it."""
    session = _setup(tmp_path, monkeypatch)
    cmd_github(session, "init")  # no remote

    # Must not raise
    cmd_github(session, "push")


def test_pull_on_non_repo_does_not_kill_repl(tmp_path, monkeypatch) -> None:
    """``/github pull`` on a project that's not initialised raises
    SystemExit(2) inside the CLI — REPL must swallow."""
    session = _setup(tmp_path, monkeypatch)
    # Do NOT init
    cmd_github(session, "pull")


def test_unknown_subcommand_reports_usage(tmp_path, monkeypatch, capsys) -> None:
    session = _setup(tmp_path, monkeypatch)
    cmd_github(session, "fly-to-moon")
    out = capsys.readouterr().out
    assert "Unknown github subcommand" in out


def test_init_delegates_via_ctx_invoke(tmp_path, monkeypatch) -> None:
    """The handler delegates to ``urika.cli.github.github_init`` via a
    ``click.Context`` so flag changes upstream propagate without
    REPL-side updates. Spies on the Click function itself."""
    session = _setup(tmp_path, monkeypatch)

    captured: dict = {}
    real_invoke = click.Context.invoke

    def _spy_invoke(self, callback, *args, **kw):  # noqa: ANN001
        captured.setdefault("calls", []).append(
            (getattr(callback, "name", str(callback)), kw)
        )
        return real_invoke(self, callback, *args, **kw)

    monkeypatch.setattr(click.Context, "invoke", _spy_invoke)

    cmd_github(session, "init")

    names = [c[0] for c in captured.get("calls", [])]
    assert any("init" in n for n in names), names
