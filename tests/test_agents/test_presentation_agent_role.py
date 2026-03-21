"""Tests for the presentation agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.presentation_agent import get_role


class TestPresentationAgentRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "presentation_agent"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert isinstance(config, AgentConfig)
        assert config.name == "presentation_agent"

    def test_config_has_read_only_tools(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert "Read" in config.allowed_tools
        assert "Glob" in config.allowed_tools
        assert "Grep" in config.allowed_tools
        assert "Write" not in config.allowed_tools
        assert "Bash" not in config.allowed_tools

    def test_security_is_read_only(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert config.security.writable_dirs == []

    def test_security_no_bash(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert config.security.allowed_bash_prefixes == []

    def test_config_has_system_prompt(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert len(config.system_prompt) > 0
        assert str(tmp_path) in config.system_prompt

    def test_prompt_contains_presentation_content(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert "slide" in config.system_prompt.lower()
        assert "presentation" in config.system_prompt.lower()

    def test_max_turns_is_10(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert config.max_turns == 10

    def test_cwd_is_project_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert config.cwd == tmp_path

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "presentation_agent" in registry.list_all()
