"""Report agent — writes narrative markdown reports from experiment results."""

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
        name="report_agent",
        description="Writes narrative research reports from experiment results",
        build_config=build_config,
    )


def format_report_context(project_dir: Path) -> str:
    """Build the per-turn user-message prefix for report_agent.

    Mirrors ``planning_agent.format_planning_context`` and
    ``advisor_agent.format_advisor_context``: returns project memory
    (MEMORY.md) + the rolling advisor context summary, formatted under
    the same ``## Project Memory & Prior Context`` heading, or an empty
    string when neither is present.

    The report agent is the project-facing narrative writer — when it
    produces the experiment report or the final write-up it must respect
    the audience preferences, terminology bans, rejected framings, and
    other user-pinned decisions that prior sessions captured. Closes the
    read-side loop that planning_agent and advisor_agent already had.

    Like its planning and advisor siblings this helper delivers the
    block via the per-turn user message rather than the system prompt,
    preserving the byte-stable system prompt that the Anthropic prompt
    cache keys on.
    """
    # Delegate to the planning helper: identical project-memory +
    # context-summary loading logic, identical heading text. Sharing
    # the implementation here means any future tweak (e.g. truncation
    # policy, new memory section) lands in one place and all three
    # reader roles inherit it.
    from urika.agents.roles.planning_agent import format_planning_context

    return format_planning_context(project_dir)


def build_config(
    project_dir: Path,
    *,
    experiment_id: str = "",
    audience: str = "standard",  # noqa: ARG001 — kept for API compat; audience now flows via the per-turn user message via ``audience.format_audience_context``
    **kwargs: object,
) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    experiment_dir = project_dir / "experiments" / experiment_id
    return AgentConfig(
        name="report_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "report_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "experiment_id": experiment_id,
                "experiment_dir": str(experiment_dir),
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
        model=get_agent_model("report_agent", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "report_agent", runtime_config),
    )
