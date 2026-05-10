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
