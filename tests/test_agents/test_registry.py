"""Tests for AgentRegistry."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.registry import AgentRegistry


def _make_role(name: str) -> AgentRole:
    def build(project_dir: Path, **kwargs: object) -> AgentConfig:
        return AgentConfig(
            name=name,
            system_prompt=f"You are {name}.",
            allowed_tools=[],
            disallowed_tools=[],
            security=SecurityPolicy(
                writable_dirs=[],
                readable_dirs=[],
                allowed_bash_prefixes=[],
                blocked_bash_patterns=[],
            ),
        )

    return AgentRole(name=name, description=f"{name} agent", build_config=build)


class TestAgentRegistry:
    def test_register_and_get(self) -> None:
        registry = AgentRegistry()
        role = _make_role("worker")
        registry.register(role)
        assert registry.get("worker") is role

    def test_get_nonexistent_returns_none(self) -> None:
        registry = AgentRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all_sorted(self) -> None:
        registry = AgentRegistry()
        registry.register(_make_role("worker"))
        registry.register(_make_role("evaluator"))
        assert registry.list_all() == ["evaluator", "worker"]

    def test_list_all_empty(self) -> None:
        registry = AgentRegistry()
        assert registry.list_all() == []

    def test_discover_finds_echo_role(self) -> None:
        """discover() should find the echo agent in roles/."""
        registry = AgentRegistry()
        registry.discover()
        names = registry.list_all()
        assert "echo" in names

    def test_register_overwrites_same_name(self) -> None:
        registry = AgentRegistry()
        role1 = _make_role("agent")
        role2 = _make_role("agent")
        registry.register(role1)
        registry.register(role2)
        assert registry.get("agent") is role2
