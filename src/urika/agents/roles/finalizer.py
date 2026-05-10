"""Finalizer agent — produces polished methods, findings, and reproducibility artifacts."""

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
        name="finalizer",
        description="Produces final polished methods, findings summary, and reproducibility artifacts",
        build_config=build_config,
    )


def build_config(
    project_dir: Path,
    *,
    experiment_id: str = "",  # noqa: ARG001 — kept for API compat with other roles
    audience: str = "standard",  # noqa: ARG001 — kept for API compat; audience now flows via the per-turn user message via ``audience.format_audience_context``
    **kwargs: object,
) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    return AgentConfig(
        name="finalizer",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "finalizer_system.md",
            variables={
                "project_dir": str(project_dir),
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[
                project_dir,
                project_dir / "methods",
                project_dir / "projectbook",
            ],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=20,
        cwd=project_dir,
        model=get_agent_model("finalizer", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "finalizer", runtime_config),
    )
