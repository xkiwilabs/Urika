"""Tool builder agent — creates reusable ITool implementations."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import (
    AgentConfig,
    AgentRole,
    SecurityPolicy,
    build_agent_env_for_endpoint,
    get_agent_model,
    load_runtime_config,
)
from urika.agents.prompt import load_prompt
from urika.core.hardware import hardware_summary

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="tool_builder",
        description="Builds project-specific tools and skills",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    tools_dir = project_dir / "tools"

    from urika.agents.roles.task_agent import _build_data_privacy_block

    data_privacy = _build_data_privacy_block(
        project_dir, runtime_config.privacy_mode
    )

    return AgentConfig(
        name="tool_builder",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "tool_builder_system.md",
            variables={
                "project_dir": str(project_dir),
                "tools_dir": str(tools_dir),
                "hardware_summary": hardware_summary(),
                "data_privacy_instructions": data_privacy,
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
        model=get_agent_model("tool_builder", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "tool_builder", runtime_config),
    )
