"""Tests for the ``_maybe_auto_push`` helper (v0.6.0 Task 2.5).

The helper is called from the tail of ``urika run`` / ``urika finalize`` /
``urika build-tool`` and is responsible for honouring ``[github]
auto_push = true`` in ``urika.toml``. It must NEVER raise — an
unexpected failure must surface as a warning rather than break the
host command.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace


def _setup(tmp_path: Path, monkeypatch) -> Path:
    """Register a project named ``proj`` rooted at ``tmp_path/proj``."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    config = ProjectConfig(
        name="proj",
        question="q",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(project_dir, config)
    ProjectRegistry().register("proj", project_dir)
    return project_dir


def _make_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    return remote


def _git_init_project(remote: Path | None = None) -> None:
    """Run ``urika github init`` for the project, optionally with a remote."""
    args = ["github", "init", "proj"]
    if remote is not None:
        args += ["--remote", str(remote)]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output


def _write_auto_push_toml(
    project_dir: Path, *, enabled: bool, events: list[str]
) -> None:
    """Overwrite ``urika.toml`` with an ``[github]`` block configured for tests."""
    events_toml = ", ".join(f'"{e}"' for e in events)
    (project_dir / "urika.toml").write_text(
        '[project]\nname = "proj"\nquestion = "q"\nmode = "exploratory"\n'
        "[github]\n"
        f"auto_push = {'true' if enabled else 'false'}\n"
        f"auto_push_after = [{events_toml}]\n",
        encoding="utf-8",
    )


def test_maybe_auto_push_fires_when_event_listed(tmp_path: Path, monkeypatch) -> None:
    """When auto_push=true and event is in auto_push_after: scan, commit, push."""
    from urika.cli.github import _maybe_auto_push

    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(remote=remote)
    _write_auto_push_toml(proj, enabled=True, events=["run", "finalize", "build-tool"])
    (proj / "exp.json").write_text('{"x": 1}\n', encoding="utf-8")

    result = _maybe_auto_push(proj, event="run")
    assert result is True

    log = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--format=%B"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "urika-event: run" in log


def test_maybe_auto_push_skipped_when_event_not_listed(
    tmp_path: Path, monkeypatch
) -> None:
    """An event NOT in auto_push_after returns False without pushing."""
    from urika.cli.github import _maybe_auto_push

    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(remote=remote)
    _write_auto_push_toml(proj, enabled=True, events=["finalize"])

    result = _maybe_auto_push(proj, event="run")
    assert result is False


def test_maybe_auto_push_skipped_when_disabled(tmp_path: Path, monkeypatch) -> None:
    """auto_push=false returns False even if event is in the list."""
    from urika.cli.github import _maybe_auto_push

    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(remote=remote)
    _write_auto_push_toml(proj, enabled=False, events=["run"])

    result = _maybe_auto_push(proj, event="run")
    assert result is False


def test_maybe_auto_push_aborts_on_secret(tmp_path: Path, monkeypatch) -> None:
    """Secret in staged content aborts auto-push; returns False; does NOT raise."""
    from urika.cli.github import _maybe_auto_push

    proj = _setup(tmp_path, monkeypatch)
    remote = _make_bare_remote(tmp_path)
    _git_init_project(remote=remote)
    _write_auto_push_toml(proj, enabled=True, events=["run"])

    (proj / "leak.py").write_text(
        "API_KEY = 'sk-ant-api03-1234567890abcdefghijklmnopqrstuvwx'\n",
        encoding="utf-8",
    )

    result = _maybe_auto_push(proj, event="run")
    assert result is False

    # No leaked commit reached the remote.
    log = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "leak" not in log.lower()


def test_maybe_auto_push_no_urika_toml() -> None:
    """Project without urika.toml: just returns False, no error."""
    from urika.cli.github import _maybe_auto_push

    with tempfile.TemporaryDirectory() as d:
        result = _maybe_auto_push(Path(d), event="run")
    assert result is False


def test_maybe_auto_push_not_a_git_repo(tmp_path: Path, monkeypatch) -> None:
    """auto_push=true but project not yet ``urika github init``'d: returns False + warns."""
    from urika.cli.github import _maybe_auto_push

    proj = _setup(tmp_path, monkeypatch)
    _write_auto_push_toml(proj, enabled=True, events=["run"])
    # Deliberately do NOT call _git_init_project — no .git/ dir.

    assert not (proj / ".git").exists()
    result = _maybe_auto_push(proj, event="run")
    assert result is False
