"""Tests for ``urika delete`` and ``urika list --prune``.

The core trash helper has its own coverage in
``tests/test_core/test_project_delete.py``; here we exercise the CLI
wrappers (confirm prompt, --force, --json, ProjectNotFoundError /
ActiveRunError surfacing, registry-only path) and the new ``--prune``
flag on ``urika list``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli
from urika.core.registry import ProjectRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def urika_env(tmp_path: Path) -> dict[str, str]:
    """URIKA_HOME redirected to tmp_path so the test never touches ~/.urika."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }


def _register_project(urika_env: dict[str, str], name: str = "foo") -> Path:
    """Create a small project dir and register it.

    Bypasses ``urika new`` (slow agent loop) — we only need a registered
    project on disk for the delete/prune commands.
    """
    import os

    old_home = os.environ.get("URIKA_HOME")
    os.environ["URIKA_HOME"] = urika_env["URIKA_HOME"]
    try:
        project = Path(urika_env["URIKA_PROJECTS_DIR"]) / name
        project.mkdir(parents=True, exist_ok=True)
        (project / "config.yaml").write_text("name: test\n", encoding="utf-8")
        (project / "experiments").mkdir(exist_ok=True)
        ProjectRegistry().register(name, project)
        return project
    finally:
        if old_home is None:
            del os.environ["URIKA_HOME"]
        else:
            os.environ["URIKA_HOME"] = old_home


def _registry_for(urika_env: dict[str, str]) -> ProjectRegistry:
    """Open a ProjectRegistry rooted at ``urika_env``'s URIKA_HOME."""
    import os

    old_home = os.environ.get("URIKA_HOME")
    os.environ["URIKA_HOME"] = urika_env["URIKA_HOME"]
    try:
        return ProjectRegistry()
    finally:
        if old_home is None:
            del os.environ["URIKA_HOME"]
        else:
            os.environ["URIKA_HOME"] = old_home


# ---------------------------------------------------------------------------
# urika delete
# ---------------------------------------------------------------------------


class TestDeleteCommand:
    def test_delete_y_confirm_trashes(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project = _register_project(urika_env, "foo")

        result = runner.invoke(cli, ["delete", "foo"], env=urika_env, input="y\n")

        assert result.exit_code == 0, result.output
        assert "Moved 'foo' to" in result.output
        # Project directory was moved
        assert not project.exists()
        # Registry entry gone
        assert _registry_for(urika_env).get("foo") is None
        # Trash dir created with the expected prefix
        trash_root = Path(urika_env["URIKA_HOME"]) / "trash"
        assert trash_root.exists()
        moved = list(trash_root.iterdir())
        assert len(moved) == 1
        assert moved[0].name.startswith("foo-")

    def test_delete_n_confirm_aborts(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project = _register_project(urika_env, "foo")

        result = runner.invoke(cli, ["delete", "foo"], env=urika_env, input="n\n")

        # click.confirm(abort=True) on 'n' raises Abort -> exit code 1
        # the command catches it and echoes 'Aborted.' before returning.
        # Either exit_code 0 (clean handling) or 1 (raw Abort) is acceptable;
        # what matters is that the project is untouched.
        assert result.exit_code in (0, 1)
        assert "Aborted" in result.output or "Aborted." in result.output
        assert project.exists()
        assert _registry_for(urika_env).get("foo") == project
        # Trash dir should not have been populated
        trash_root = Path(urika_env["URIKA_HOME"]) / "trash"
        assert not trash_root.exists() or list(trash_root.iterdir()) == []

    def test_delete_force_skips_prompt(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project = _register_project(urika_env, "foo")

        result = runner.invoke(cli, ["delete", "foo", "--force"], env=urika_env)

        assert result.exit_code == 0, result.output
        assert "Moved 'foo' to" in result.output
        assert not project.exists()
        assert _registry_for(urika_env).get("foo") is None

    def test_delete_unknown_name_exits_with_error(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["delete", "nonexistent", "--force"], env=urika_env)

        assert result.exit_code != 0
        assert "not registered" in result.output

    def test_delete_active_lock_exits_with_error(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project = _register_project(urika_env, "foo")
        lock_dir = project / "experiments" / "exp-001"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / ".lock"
        lock_path.write_text("pid:1234\n", encoding="utf-8")

        result = runner.invoke(cli, ["delete", "foo", "--force"], env=urika_env)

        assert result.exit_code != 0
        assert str(lock_path) in result.output
        # Project untouched
        assert project.exists()
        assert _registry_for(urika_env).get("foo") == project

    def test_delete_missing_folder_unregisters_silently(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        # Register a path that was never created on disk
        ghost = Path(urika_env["URIKA_PROJECTS_DIR"]) / "ghost"
        reg = _registry_for(urika_env)
        reg.register("foo", ghost)
        assert not ghost.exists()

        result = runner.invoke(cli, ["delete", "foo", "--force"], env=urika_env)

        assert result.exit_code == 0, result.output
        assert "Unregistered" in result.output
        assert "foo" in result.output
        assert _registry_for(urika_env).get("foo") is None

    def test_delete_json_output(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        project = _register_project(urika_env, "foo")

        result = runner.invoke(
            cli, ["delete", "foo", "--force", "--json"], env=urika_env
        )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["name"] == "foo"
        assert data["original_path"] == str(project)
        assert data["registry_only"] is False
        assert isinstance(data["trash_path"], str)
        # trash_path should live under <URIKA_HOME>/trash/ and start with the name
        trash_root = Path(urika_env["URIKA_HOME"]) / "trash"
        assert Path(data["trash_path"]).parent == trash_root
        assert Path(data["trash_path"]).name.startswith("foo-")
        assert Path(data["trash_path"]).exists()


# ---------------------------------------------------------------------------
# urika list --prune
# ---------------------------------------------------------------------------


class TestListPrune:
    def test_list_prune_removes_missing_entries(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        # Two registered projects: one real, one ghost
        real = _register_project(urika_env, "real")
        ghost = Path(urika_env["URIKA_PROJECTS_DIR"]) / "ghost"
        _registry_for(urika_env).register("ghost", ghost)
        assert not ghost.exists()

        result = runner.invoke(cli, ["list", "--prune"], env=urika_env)

        assert result.exit_code == 0, result.output
        assert "Pruned" in result.output
        assert "ghost" in result.output
        # Real project is still listed afterwards
        assert "real" in result.output

        reg = _registry_for(urika_env)
        assert reg.get("ghost") is None
        assert reg.get("real") == real

    def test_list_prune_no_stale_entries(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _register_project(urika_env, "real")

        result = runner.invoke(cli, ["list", "--prune"], env=urika_env)

        assert result.exit_code == 0, result.output
        assert "No stale entries" in result.output
        assert "real" in result.output

    def test_list_without_prune_unchanged(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        # Register one valid + one ghost; without --prune both should remain.
        _register_project(urika_env, "real")
        ghost = Path(urika_env["URIKA_PROJECTS_DIR"]) / "ghost"
        _registry_for(urika_env).register("ghost", ghost)

        result = runner.invoke(cli, ["list"], env=urika_env)

        assert result.exit_code == 0, result.output
        assert "real" in result.output
        assert "ghost" in result.output
        # Registry untouched
        reg = _registry_for(urika_env)
        assert reg.get("real") is not None
        assert reg.get("ghost") is not None
