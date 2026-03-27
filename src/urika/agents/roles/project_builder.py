"""Project builder agent — scopes new projects by analysing data."""

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

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="project_builder",
        description="Analyses data and generates clarifying questions for project setup",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    return AgentConfig(
        name="project_builder",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "project_builder_system.md",
            variables={
                "project_dir": str(project_dir),
            },
        ),
        allowed_tools=["Read", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=10,
        cwd=project_dir,
        model=get_agent_model("project_builder", runtime_config),
        env=build_agent_env_for_endpoint(
            project_dir, "project_builder", runtime_config
        ),
    )
