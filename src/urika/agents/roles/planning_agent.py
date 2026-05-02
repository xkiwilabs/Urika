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

    # v0.4 Track 2: inject (a) project memory ``MEMORY.md`` block and
    # (b) the rolling context summary into the planner's system
    # prompt. Memory persists across sessions; context summary is
    # in-loop. Both prefix the base prompt — the planner sees user
    # preferences first, then prior conversation, then its own
    # role instructions.
    from urika.core.advisor_memory import load_context_summary
    from urika.core.project_memory import load_project_memory

    project_memory = load_project_memory(project_dir)
    context_summary = load_context_summary(project_dir) or ""
    base_prompt = load_prompt(
        _PROMPTS_DIR / "planning_agent_system.md",
        variables={
            "project_dir": str(project_dir),
            "experiment_id": experiment_id,
            "experiment_dir": str(experiment_dir),
        },
    )
    prefix_parts = []
    if project_memory:
        prefix_parts.append(project_memory.rstrip())
    if context_summary:
        prefix_parts.append(
            f"## Prior conversation summary\n\n{context_summary}"
        )
    if prefix_parts:
        system_prompt = "\n\n---\n\n".join(prefix_parts) + "\n\n---\n\n" + base_prompt
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
