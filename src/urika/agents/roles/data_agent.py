"""Data agent — reads raw data and outputs sanitized summaries."""

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
        name="data_agent",
        description="Reads raw data and outputs sanitized summaries and features",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    data_dir = project_dir / "data"
    experiments_dir = project_dir / "experiments"

    return AgentConfig(
        name="data_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "data_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "data_dir": str(data_dir),
            },
        ),
        allowed_tools=["Read", "Bash", "Glob", "Grep", "Write"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[experiments_dir, data_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=10,
        cwd=project_dir,
        model=get_agent_model("data_agent", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "data_agent", runtime_config),
    )
