"""Planning agent — designs analytical method pipelines."""

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
        name="planning_agent",
        description="Designs complete analytical method pipelines",
        build_config=build_config,
    )


def build_config(
    project_dir: Path, *, experiment_id: str = "", **kwargs: object
) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    experiment_dir = project_dir / "experiments" / experiment_id

    # v0.4 Track 2 cheap win: inject the rolling context summary
    # into the planner's system prompt. Pre-v0.4 only the advisor
    # received this summary; the planner had to rediscover prior
    # decisions from advisor-history.json on its own. Same pattern
    # already proven at ``loop.py:611-614``.
    from urika.core.advisor_memory import load_context_summary

    context_summary = load_context_summary(project_dir) or ""
    base_prompt = load_prompt(
        _PROMPTS_DIR / "planning_agent_system.md",
        variables={
            "project_dir": str(project_dir),
            "experiment_id": experiment_id,
            "experiment_dir": str(experiment_dir),
        },
    )
    if context_summary:
        system_prompt = (
            f"## Prior conversation summary\n\n{context_summary}\n\n"
            f"---\n\n{base_prompt}"
        )
    else:
        system_prompt = base_prompt

    return AgentConfig(
        name="planning_agent",
        system_prompt=system_prompt,
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
        model=get_agent_model("planning_agent", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "planning_agent", runtime_config),
    )
