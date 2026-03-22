"""Tests for REPL slash command handlers."""
from __future__ import annotations
from pathlib import Path

from urika.repl_commands import (
    GLOBAL_COMMANDS,
    PROJECT_COMMANDS,
    get_all_commands,
    get_command_names,
)
from urika.repl_session import ReplSession


class TestCommandRegistration:
    def test_global_commands_has_expected_keys(self) -> None:
        expected = {"help", "projects", "project", "new", "quit"}
        assert expected.issubset(set(GLOBAL_COMMANDS.keys()))

    def test_project_commands_has_expected_keys(self) -> None:
        expected = {
            "status", "run", "experiments", "methods",
            "criteria", "present", "report", "inspect",
            "logs", "knowledge",
        }
        assert expected.issubset(set(PROJECT_COMMANDS.keys()))

    def test_all_commands_have_func_and_description(self) -> None:
        for name, entry in {**GLOBAL_COMMANDS, **PROJECT_COMMANDS}.items():
            assert "func" in entry, f"Command '{name}' missing 'func'"
            assert "description" in entry, f"Command '{name}' missing 'description'"
            assert callable(entry["func"]), f"Command '{name}' func not callable"
            assert isinstance(entry["description"], str), f"Command '{name}' description not str"


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
