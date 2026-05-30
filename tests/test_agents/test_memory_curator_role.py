"""Tests for the memory_curator agent role.

The memory_curator (Task 2.4 of the v0.5.0 memory-deepening plan) is an
EMIT-ONLY role: given the contents of the project's memory directory it
proposes merge / archive / flag decisions as a JSON object. It must not
touch the filesystem itself — apply logic lives in T2.6.
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole
from urika.agents.registry import AgentRegistry
from urika.agents.roles.memory_curator import build_config, get_role


class TestMemoryCuratorRole:
    def test_get_role_returns_agent_role(self) -> None:
        role = get_role()
        assert isinstance(role, AgentRole)
        assert role.name == "memory_curator"

    def test_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        config = build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "memory_curator"

    def test_role_build_config_returns_agent_config(self, tmp_path: Path) -> None:
        role = get_role()
        config = role.build_config(tmp_path)
        assert isinstance(config, AgentConfig)
        assert config.name == "memory_curator"

    def test_system_prompt_mentions_memory_and_curator_job(
        self, tmp_path: Path
    ) -> None:
        config = build_config(tmp_path)
        sp = config.system_prompt
        assert len(sp) > 0
        sp_lower = sp.lower()
        assert "memory" in sp_lower
        # The curator's job centres on merge / archive / flag decisions.
        assert "merge" in sp_lower
        assert "archive" in sp_lower
        assert "flag" in sp_lower

    def test_system_prompt_describes_json_output_shape(self, tmp_path: Path) -> None:
        """Output contract — the prompt must instruct the model to return JSON."""
        config = build_config(tmp_path)
        sp = config.system_prompt
        assert "json" in sp.lower()
        assert "decisions" in sp.lower()

    def test_no_filesystem_tools(self, tmp_path: Path) -> None:
        """Curator only emits decisions — no Read/Write/Bash tools."""
        config = build_config(tmp_path)
        # Emit-only: no tool access whatsoever. The contents of the memory
        # directory are handed to the curator via the per-turn user
        # message, not by letting it browse the filesystem.
        assert config.allowed_tools == []
        assert "Read" not in config.allowed_tools
        assert "Write" not in config.allowed_tools
        assert "Bash" not in config.allowed_tools
        assert "Edit" not in config.allowed_tools
        assert "Glob" not in config.allowed_tools
        assert "Grep" not in config.allowed_tools

    def test_security_is_empty(self, tmp_path: Path) -> None:
        """SecurityPolicy must grant nothing — defence in depth."""
        config = build_config(tmp_path)
        assert config.security.writable_dirs == []
        assert config.security.readable_dirs == []
        assert config.security.allowed_bash_prefixes == []
        assert config.security.blocked_bash_patterns == []

    def test_discoverable_by_registry(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        assert "memory_curator" in registry.list_all()

    def test_registry_get_returns_curator_role(self) -> None:
        registry = AgentRegistry()
        registry.discover()
        role = registry.get("memory_curator")
        assert role is not None
        assert role.name == "memory_curator"
