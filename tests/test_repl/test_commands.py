"""Tests for REPL slash command handlers."""

from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock

import click

from urika.repl_commands import (
    GLOBAL_COMMANDS,
    PROJECT_COMMANDS,
    cmd_delete,
    cmd_new,
    get_all_commands,
    get_command_names,
)
from urika.repl_session import ReplSession


class TestCommandRegistration:
    def test_global_commands_has_expected_keys(self) -> None:
        expected = {"help", "list", "project", "new", "quit"}
        assert expected.issubset(set(GLOBAL_COMMANDS.keys()))

    def test_project_commands_has_expected_keys(self) -> None:
        expected = {
            "status",
            "run",
            "experiments",
            "methods",
            "criteria",
            "present",
            "report",
            "inspect",
            "logs",
            "knowledge",
        }
        assert expected.issubset(set(PROJECT_COMMANDS.keys()))

    def test_all_commands_have_func_and_description(self) -> None:
        for name, entry in {**GLOBAL_COMMANDS, **PROJECT_COMMANDS}.items():
            assert "func" in entry, f"Command '{name}' missing 'func'"
            assert "description" in entry, f"Command '{name}' missing 'description'"
            assert callable(entry["func"]), f"Command '{name}' func not callable"
            assert isinstance(entry["description"], str), (
                f"Command '{name}' description not str"
            )


class TestGetCommandNames:
    def test_returns_sorted_list(self) -> None:
        session = ReplSession()
        names = get_command_names(session)
        assert names == sorted(names)

    def test_global_only_without_project(self) -> None:
        session = ReplSession()
        names = get_command_names(session)
        # Should include global commands
        assert "help" in names
        assert "quit" in names
        # Should NOT include project commands
        assert "status" not in names
        assert "run" not in names

    def test_includes_project_commands_with_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "test-project")
        names = get_command_names(session)
        # Should include both global and project commands
        assert "help" in names
        assert "status" in names
        assert "run" in names
        assert "experiments" in names


class TestGetAllCommands:
    def test_global_only_without_project(self) -> None:
        session = ReplSession()
        cmds = get_all_commands(session)
        assert "help" in cmds
        assert "status" not in cmds

    def test_includes_project_commands_with_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "test-project")
        cmds = get_all_commands(session)
        assert "help" in cmds
        assert "status" in cmds
        assert "run" in cmds
        assert "knowledge" in cmds


class TestCmdNew:
    """Tests for the /new command handler."""

    def test_passes_name_from_args(self, tmp_path: Path) -> None:
        """When args contain a name, it should be passed to ctx.invoke."""
        session = ReplSession()
        invoked_kwargs = {}

        def fake_invoke(func, **kwargs):
            invoked_kwargs.update(kwargs)

        with (
            patch("urika.repl_commands.click.Context") as mock_ctx_cls,
            patch("urika.core.registry.ProjectRegistry") as mock_reg_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx
            # Registry returns empty before and after (no project created)
            mock_reg = MagicMock()
            mock_reg.list_all.return_value = {}
            mock_reg_cls.return_value = mock_reg

            cmd_new(session, "my-project")

        assert invoked_kwargs["name"] == "my-project"

    def test_passes_none_when_no_args(self, tmp_path: Path) -> None:
        """When args are empty, name should be None."""
        session = ReplSession()
        invoked_kwargs = {}

        def fake_invoke(func, **kwargs):
            invoked_kwargs.update(kwargs)

        with (
            patch("urika.repl_commands.click.Context") as mock_ctx_cls,
            patch("urika.core.registry.ProjectRegistry") as mock_reg_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx
            mock_reg = MagicMock()
            mock_reg.list_all.return_value = {}
            mock_reg_cls.return_value = mock_reg

            cmd_new(session, "")

        assert invoked_kwargs["name"] is None

    def test_auto_loads_created_project(self, tmp_path: Path) -> None:
        """After a project is created, it should be loaded into the session."""
        session = ReplSession()
        project_path = tmp_path / "new-proj"
        project_path.mkdir()

        def fake_invoke(func, **kwargs):
            pass  # Simulate successful project creation

        with (
            patch("urika.repl_commands.click.Context") as mock_ctx_cls,
            patch("urika.core.registry.ProjectRegistry") as mock_reg_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx

            # First call (before): empty registry
            # Second call (after): one project registered
            mock_reg_before = MagicMock()
            mock_reg_before.list_all.return_value = {}
            mock_reg_after = MagicMock()
            mock_reg_after.list_all.return_value = {"new-proj": project_path}

            mock_reg_cls.side_effect = [mock_reg_before, mock_reg_after]

            cmd_new(session, "")

        assert session.has_project
        assert session.project_name == "new-proj"
        assert session.project_path == project_path

    def test_no_load_when_creation_aborted(self, tmp_path: Path) -> None:
        """If no new project appears in registry, session stays unchanged."""
        session = ReplSession()

        def fake_invoke(func, **kwargs):
            pass  # Simulate aborted creation (user cancelled)

        with (
            patch("urika.repl_commands.click.Context") as mock_ctx_cls,
            patch("urika.core.registry.ProjectRegistry") as mock_reg_cls,
        ):
            mock_ctx = MagicMock()
            mock_ctx.invoke = fake_invoke
            mock_ctx_cls.return_value = mock_ctx

            # Both before and after return the same projects (nothing new)
            mock_reg = MagicMock()
            mock_reg.list_all.return_value = {"existing": tmp_path}
            mock_reg_cls.return_value = mock_reg

            cmd_new(session, "")

        assert not session.has_project


class TestCmdDelete:
    """Tests for the /delete command handler."""

    def test_empty_args_prints_usage(self, capsys) -> None:
        session = ReplSession()
        cmd_delete(session, "")
        out = capsys.readouterr().out
        assert "Usage: /delete" in out

    def test_confirms_then_trashes(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """User confirms 'y'; trash_project is called; success line printed."""
        session = ReplSession()
        proj = tmp_path / "foo"
        proj.mkdir()

        from urika.core.project_delete import TrashResult

        called = {}

        def fake_trash(name):
            called["name"] = name
            return TrashResult(
                name=name,
                original_path=proj,
                trash_path=tmp_path / "trash" / "foo-x",
                registry_only=False,
            )

        monkeypatch.setattr(
            "urika.core.project_delete.trash_project", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete(session, "foo")

        assert called["name"] == "foo"
        assert "Moved 'foo' to" in capsys.readouterr().out

    def test_n_aborts_without_calling_trash(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        session = ReplSession()
        called = {"hit": False}

        def fake_trash(name):
            called["hit"] = True

        def fake_confirm(*a, **kw):
            raise click.Abort()

        monkeypatch.setattr(
            "urika.core.project_delete.trash_project", fake_trash
        )
        monkeypatch.setattr("click.confirm", fake_confirm)
        cmd_delete(session, "foo")
        assert called["hit"] is False
        assert "Aborted." in capsys.readouterr().out

    def test_unknown_project_prints_error(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.core.project_delete import ProjectNotFoundError

        session = ReplSession()

        def fake_trash(name):
            raise ProjectNotFoundError(name)

        monkeypatch.setattr(
            "urika.core.project_delete.trash_project", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete(session, "ghost")
        assert "not registered" in capsys.readouterr().out

    def test_active_lock_prints_error(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.core.project_delete import ActiveRunError

        session = ReplSession()

        def fake_trash(name):
            raise ActiveRunError(tmp_path / "exp/.lock")

        monkeypatch.setattr(
            "urika.core.project_delete.trash_project", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete(session, "foo")
        out = capsys.readouterr().out
        assert ".lock" in out

    def test_clears_session_when_deleting_loaded_project(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.core.project_delete import TrashResult

        session = ReplSession()
        session.load_project(tmp_path, "foo")
        assert session.has_project

        def fake_trash(name):
            return TrashResult(
                name=name,
                original_path=tmp_path,
                trash_path=tmp_path / "trash" / "foo-x",
                registry_only=False,
            )

        monkeypatch.setattr(
            "urika.core.project_delete.trash_project", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete(session, "foo")
        assert not session.has_project
        assert "context cleared" in capsys.readouterr().out

    def test_registry_only_message_when_folder_missing(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.core.project_delete import TrashResult

        session = ReplSession()
        gone = tmp_path / "gone"

        def fake_trash(name):
            return TrashResult(
                name=name,
                original_path=gone,
                trash_path=None,
                registry_only=True,
            )

        monkeypatch.setattr(
            "urika.core.project_delete.trash_project", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete(session, "foo")
        out = capsys.readouterr().out
        assert "Unregistered 'foo'" in out
        assert "already missing" in out


class TestCmdDeleteExperiment:
    """Tests for the /delete-experiment slash command (TUI/REPL)."""

    def test_empty_args_prints_usage(self, tmp_path: Path, capsys) -> None:
        from urika.repl_commands import cmd_delete_experiment

        session = ReplSession()
        session.load_project(tmp_path, "foo")
        cmd_delete_experiment(session, "")
        out = capsys.readouterr().out
        assert "Usage: /delete-experiment" in out

    def test_confirms_then_trashes(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.repl_commands import cmd_delete_experiment
        from urika.core.experiment_delete import TrashExperimentResult

        session = ReplSession()
        session.load_project(tmp_path, "foo")
        called: dict = {}

        def fake_trash(project_path, project_name, exp_id):
            called["args"] = (project_path, project_name, exp_id)
            return TrashExperimentResult(
                project_name=project_name,
                experiment_id=exp_id,
                original_path=project_path / "experiments" / exp_id,
                trash_path=project_path / "trash" / f"{exp_id}-x",
            )

        monkeypatch.setattr(
            "urika.core.experiment_delete.trash_experiment", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete_experiment(session, "exp-001")

        assert called["args"][1] == "foo"
        assert called["args"][2] == "exp-001"
        assert "Moved 'exp-001' to" in capsys.readouterr().out

    def test_n_aborts_without_calling_trash(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.repl_commands import cmd_delete_experiment

        session = ReplSession()
        session.load_project(tmp_path, "foo")
        called: dict = {"hit": False}

        def fake_trash(*a, **kw):
            called["hit"] = True

        def fake_confirm(*a, **kw):
            raise click.Abort()

        monkeypatch.setattr(
            "urika.core.experiment_delete.trash_experiment", fake_trash
        )
        monkeypatch.setattr("click.confirm", fake_confirm)
        cmd_delete_experiment(session, "exp-001")
        assert called["hit"] is False
        assert "Aborted." in capsys.readouterr().out

    def test_unknown_experiment_prints_error(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.repl_commands import cmd_delete_experiment
        from urika.core.experiment_delete import ExperimentNotFoundError

        session = ReplSession()
        session.load_project(tmp_path, "foo")

        def fake_trash(project_path, project_name, exp_id):
            raise ExperimentNotFoundError(exp_id)

        monkeypatch.setattr(
            "urika.core.experiment_delete.trash_experiment", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete_experiment(session, "exp-ghost")
        assert "not found" in capsys.readouterr().out

    def test_active_lock_prints_error(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        from urika.repl_commands import cmd_delete_experiment
        from urika.core.experiment_delete import ActiveExperimentError

        session = ReplSession()
        session.load_project(tmp_path, "foo")

        def fake_trash(project_path, project_name, exp_id):
            raise ActiveExperimentError(tmp_path / "exp/.lock")

        monkeypatch.setattr(
            "urika.core.experiment_delete.trash_experiment", fake_trash
        )
        monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
        cmd_delete_experiment(session, "exp-001")
        assert ".lock" in capsys.readouterr().out


class TestFormatRelative:
    """Tests for the _format_relative timedelta humanizer."""

    def test_humanizes_timedelta(self) -> None:
        from datetime import timedelta
        from urika.repl.commands import _format_relative

        assert _format_relative(timedelta(seconds=30)) == "just now"
        assert _format_relative(timedelta(minutes=1)) == "1 minute ago"
        assert _format_relative(timedelta(minutes=5)) == "5 minutes ago"
        assert _format_relative(timedelta(hours=1)) == "1 hour ago"
        assert _format_relative(timedelta(hours=3)) == "3 hours ago"
        assert _format_relative(timedelta(days=2)) == "2 days ago"
        assert _format_relative(timedelta(days=45)) == "1 month ago"
        assert _format_relative(timedelta(days=400)) == "1 year ago"


class TestCmdProjectSessionHint:
    """Tests for the project-switch hook that surfaces the most recent
    orchestrator session with a relative-time + preview snippet."""

    def _make_project(self, tmp_path: Path, name: str = "demo") -> Path:
        """Write a minimal urika.toml so load_project_config succeeds."""
        from urika.core.models import ProjectConfig
        from urika.core.workspace import _write_toml

        project_path = tmp_path / name
        project_path.mkdir(parents=True, exist_ok=True)
        config = ProjectConfig(
            name=name,
            question="Why is the sky blue?",
            mode="exploratory",
        )
        _write_toml(project_path / "urika.toml", config.to_toml_dict())
        return project_path

    def test_shows_session_preview_inline(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """When a recent session has a preview, the hook shows it inline
        with a relative-time stamp and the resume prompt."""
        from datetime import datetime, timedelta, timezone

        from urika.core.orchestrator_sessions import (
            OrchestratorSession,
            save_session,
        )
        from urika.repl.commands import cmd_project

        project_path = self._make_project(tmp_path, "demo")

        # Persist a session whose updated time is ~2 hours ago.
        two_hours_ago = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        s = OrchestratorSession(
            session_id="20260428-160000",
            started=two_hours_ago,
            updated=two_hours_ago,
            preview="Why are tree counts so skewed in this dataset",
        )
        save_session(project_path, s)
        # save_session bumps `updated` to now; rewrite directly so we
        # actually test the relative-time path.
        import json

        sf = project_path / ".urika" / "sessions" / "20260428-160000.json"
        data = json.loads(sf.read_text())
        data["updated"] = two_hours_ago
        sf.write_text(json.dumps(data, indent=2))

        # Stub the registry so the command finds our project.
        class FakeRegistry:
            def __init__(self, *a, **kw) -> None:
                pass

            def get(self, _name: str) -> Path:
                return project_path

        monkeypatch.setattr(
            "urika.core.registry.ProjectRegistry", FakeRegistry
        )

        session = ReplSession()
        cmd_project(session, "demo")

        out = capsys.readouterr().out
        assert "tree counts so skewed" in out
        assert "/resume-session" in out
        # Relative-time fragment present (matches "2 hours ago" or close).
        assert "hour" in out or "hours" in out

    def test_no_session_no_hint(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """When the project has no sessions, no hint is printed."""
        from urika.repl.commands import cmd_project

        project_path = self._make_project(tmp_path, "empty")

        class FakeRegistry:
            def __init__(self, *a, **kw) -> None:
                pass

            def get(self, _name: str) -> Path:
                return project_path

        monkeypatch.setattr(
            "urika.core.registry.ProjectRegistry", FakeRegistry
        )

        session = ReplSession()
        cmd_project(session, "empty")
        out = capsys.readouterr().out
        assert "Previous session" not in out
        assert "/resume-session" not in out
