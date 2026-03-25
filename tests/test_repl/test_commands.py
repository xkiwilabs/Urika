"""Tests for REPL slash command handlers."""

from __future__ import annotations
from pathlib import Path
from unittest.mock import patch, MagicMock

from urika.repl_commands import (
    GLOBAL_COMMANDS,
    PROJECT_COMMANDS,
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
