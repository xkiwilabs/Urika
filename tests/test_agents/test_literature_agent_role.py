"""Tests for the literature agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.literature_agent import get_role


class TestLiteratureAgentRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "literature_agent"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "literature_agent"

    def test_config_has_write_and_bash_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert "Read" in config.allowed_tools
        assert "Write" in config.allowed_tools
        assert "Bash" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools

    def test_config_security_writable_knowledge_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        knowledge_dir = tmp_path / "knowledge"
        assert any(
            d.resolve() == knowledge_dir.resolve()
            for d in config.security.writable_dirs
        )

    def test_config_security_bash_restricted(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.security.is_bash_allowed("python script.py")
        assert config.security.is_bash_allowed("pip install pypdf")
        assert not config.security.is_bash_allowed("rm -rf /")
        assert not config.security.is_bash_allowed("git push")

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert len(config.system_prompt) > 0
        assert str(tmp_path) in config.system_prompt
        assert str(tmp_path / "knowledge") in config.system_prompt

    def test_config_cwd_is_project_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.cwd == tmp_path

    def test_config_max_turns(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert config.max_turns == 15

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "literature_agent" in registry.list_all()
