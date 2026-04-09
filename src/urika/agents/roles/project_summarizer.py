"""Project summarizer agent — produces a comprehensive project status summary."""

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
        name="project_summarizer",
        description="Summarizes project status, experiments, methods, and findings",
        build_config=build_config,
    )


def build_config(
    project_dir: Path,
    *,
    experiment_id: str = "",
    **kwargs: object,
) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)

    # Load project config for prompt variables
    from urika.core.workspace import load_project_config

    try:
        project_config = load_project_config(project_dir)
        project_name = project_config.name
        question = project_config.question
    except FileNotFoundError:
        project_name = project_dir.name
        question = ""

    data_dir = str(project_dir / "data")

    return AgentConfig(
        name="project_summarizer",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "project_summarizer_system.md",
            variables={
                "project_name": project_name,
                "question": question,
                "data_dir": data_dir,
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
        max_turns=15,
        cwd=project_dir,
        model=get_agent_model("project_summarizer", runtime_config),
        env=build_agent_env_for_endpoint(
            project_dir, "project_summarizer", runtime_config
        ),
    )
