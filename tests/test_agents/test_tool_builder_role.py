"""Tests for the tool builder agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.tool_builder import get_role


class TestToolBuilderRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "tool_builder"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "tool_builder"

    def test_config_has_write_and_bash_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert "Read" in config.allowed_tools
        assert "Write" in config.allowed_tools
        assert "Bash" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools

    def test_security_writable_tools_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        tools_dir = tmp_path / "tools"
        assert tools_dir in config.security.writable_dirs

    def test_security_bash_restricted(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.security.is_bash_allowed("python test_tool.py")
        assert config.security.is_bash_allowed("pip install numpy")
        assert config.security.is_bash_allowed("pytest tests/")
        assert not config.security.is_bash_allowed("rm -rf /")
        assert not config.security.is_bash_allowed("git push origin main")
        assert not config.security.is_bash_allowed("git reset --hard")

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert len(config.system_prompt) > 0
        assert str(tmp_path) in config.system_prompt

    def test_max_turns_is_15(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.max_turns == 15

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "tool_builder" in registry.list_all()
