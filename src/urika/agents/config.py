"""Agent configuration and security policy — runtime-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class SecurityPolicy:
    """Filesystem and command boundaries for an agent."""

    writable_dirs: list[Path]
    readable_dirs: list[
        Path
    ]  # Informational only — read enforcement deferred to future phase
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


@dataclass
class AgentConfig:
    """What an agent needs to run — runtime-agnostic."""

    name: str
    system_prompt: str
    allowed_tools: list[str]
    disallowed_tools: list[str]
    security: SecurityPolicy
    max_turns: int = 50
    model: str | None = None
    cwd: Path | None = None
    env: dict[str, str] | None = None  # environment vars for agent subprocess


@dataclass
class RuntimeConfig:
    """Project-level runtime configuration."""

    backend: str = "claude"
    model: str = ""
    model_overrides: dict[str, str] = field(default_factory=dict)
    privacy_mode: str = "cloud"  # cloud | local | hybrid


def load_runtime_config(project_dir: Path) -> RuntimeConfig:
    """Load runtime config from urika.toml. Returns defaults if not configured."""
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return RuntimeConfig()
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        runtime = data.get("runtime", {})
        return RuntimeConfig(
            backend=runtime.get("backend", "claude"),
            model=runtime.get("model", ""),
            model_overrides=runtime.get("models", {}),
            privacy_mode=data.get("privacy", {}).get("mode", "cloud"),
        )
    except Exception:
        return RuntimeConfig()


def build_agent_env(project_dir: Path) -> dict[str, str] | None:
    """Get venv environment for agents, if project has one configured."""
    from urika.core.venv import get_venv_env

    return get_venv_env(project_dir)


@dataclass
class AgentRole:
    """Definition of an agent role."""

    name: str
    description: str
    build_config: Callable[..., AgentConfig]
