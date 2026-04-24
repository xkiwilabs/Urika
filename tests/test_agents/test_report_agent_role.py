"""Tests for the report agent role."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.report_agent import get_role


class TestReportAgentRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "report_agent"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert isinstance(config, AgentConfig)
        assert config.name == "report_agent"

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

    def test_prompt_contains_report_content(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert "report" in config.system_prompt.lower()
        assert "narrative" in config.system_prompt.lower()

    def test_max_turns_is_15(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert config.max_turns == 15

    def test_cwd_is_project_dir(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        assert config.cwd == tmp_path

    def test_novice_audience_includes_plain_language(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001", audience="novice")
        assert "plain language" in config.system_prompt

    def test_expert_audience_includes_domain_expertise(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001", audience="expert")
        assert "domain expertise" in config.system_prompt

    def test_default_audience_is_standard(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path, experiment_id="exp-001")
        # 'standard' audience (the new default) emphasises verbose speaker
        # notes over concise bullets — contrast against 'expert' which says
        # "domain expertise" / "concise".
        assert "Notes are where the real explanation lives" in config.system_prompt
        assert "domain expertise" not in config.system_prompt

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "report_agent" in registry.list_all()
