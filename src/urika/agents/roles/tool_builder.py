"""Tool builder agent — creates reusable ITool implementations."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy, build_agent_env
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="tool_builder",
        description="Builds project-specific tools and skills",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    tools_dir = project_dir / "tools"
    return AgentConfig(
        name="tool_builder",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "tool_builder_system.md",
            variables={
                "project_dir": str(project_dir),
                "tools_dir": str(tools_dir),
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[tools_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip ", "pytest "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=15,
        cwd=project_dir,
        env=build_agent_env(project_dir),
    )
