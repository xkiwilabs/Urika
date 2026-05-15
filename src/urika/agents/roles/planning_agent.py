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


def format_planning_context(project_dir: Path) -> str:
    """Build the per-turn user-message prefix for planning_agent.

    Returns project memory (MEMORY.md) + the rolling advisor context
    summary, formatted as a "Project Memory & Prior Context" block,
    or empty string if neither exists.

    Pre-this-helper the planning_agent's ``build_config`` *prepended*
    these to the system prompt — which meant any change to either
    (a new memory entry, an advisor session producing a fresh
    summary) busted the cache for the entire 5.9KB base system
    prompt. Anthropic's ephemeral cache keys on the longest common
    prefix; with variable content at the top, the prefix was
    effectively zero. Moving these to the per-turn user message
    keeps the system prompt byte-stable across sessions, restoring
    cache reuse for the bulk of the prompt while still ensuring the
    planner sees the same authoritative context (it just arrives
    via the user message instead of the system role).
    """
    from urika.core.advisor_memory import load_context_summary
    from urika.core.project_memory import load_project_memory

    project_memory = load_project_memory(project_dir)
    context_summary = load_context_summary(project_dir) or ""

    parts: list[str] = []
    if project_memory:
        parts.append(project_memory.rstrip())
    if context_summary:
        parts.append(f"## Prior conversation summary\n\n{context_summary}")

    if not parts:
        return ""
    return (
        "## Project Memory & Prior Context\n\n"
        "(The following context comes from your project memory and the "
        "rolling advisor conversation summary. Treat it as authoritative "
        "user preferences and prior decisions when designing the next "
        "method.)\n\n" + "\n\n---\n\n".join(parts) + "\n\n---\n\n"
    )


def build_config(
    project_dir: Path, *, experiment_id: str = "", **kwargs: object
) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    experiment_dir = project_dir / "experiments" / experiment_id

    base_prompt = load_prompt(
        _PROMPTS_DIR / "planning_agent_system.md",
        variables={
            "project_dir": str(project_dir),
            "experiment_id": experiment_id,
            "experiment_dir": str(experiment_dir),
        },
    )

    return AgentConfig(
        name="planning_agent",
        system_prompt=base_prompt,
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
