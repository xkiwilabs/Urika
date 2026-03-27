"""Agent registry with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil

from urika.agents.config import AgentRole


class AgentRegistry:
    """Registry for agent role definitions with auto-discovery."""

    def __init__(self) -> None:
        self._roles: dict[str, AgentRole] = {}

    def register(self, role: AgentRole) -> None:
        self._roles[role.name] = role

    def get(self, name: str) -> AgentRole | None:
        return self._roles.get(name)

    def list_all(self) -> list[str]:
        return sorted(self._roles.keys())

    def discover(self) -> None:
        """Auto-discover agent roles from roles/ submodules."""
        import urika.agents.roles as roles_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(roles_pkg.__path__):
            module = importlib.import_module(f"urika.agents.roles.{modname}")
            get_role = getattr(module, "get_role", None)
            if callable(get_role):
                role = get_role()
                if isinstance(role, AgentRole):
                    self._roles[role.name] = role
