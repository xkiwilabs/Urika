"""Agent configuration and security policy — runtime-agnostic."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SecurityPolicy:
    """Filesystem and command boundaries for an agent."""

    writable_dirs: list[Path]
    readable_dirs: list[Path]
    allowed_bash_prefixes: list[str]
    blocked_bash_patterns: list[str]

    def is_write_allowed(self, path: Path) -> bool:
        """Check if a file path is within any writable directory."""
        resolved = path.resolve()
        return any(
            resolved == d.resolve() or _is_relative_to(resolved, d.resolve())
            for d in self.writable_dirs
        )

    def is_bash_allowed(self, command: str) -> bool:
        """Check if a bash command is allowed by prefix rules and not blocked."""
        cmd = command.strip()
        for pattern in self.blocked_bash_patterns:
            if pattern in cmd:
                return False
        if not self.allowed_bash_prefixes:
            return True
        return any(cmd.startswith(prefix) for prefix in self.allowed_bash_prefixes)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Check if path is relative to parent."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
