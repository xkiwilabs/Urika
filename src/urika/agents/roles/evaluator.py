"""Evaluator agent — read-only scoring of experiment results."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="evaluator",
        description="Scores experiment results against success criteria",
        build_config=build_config,
    )


def build_config(
    project_dir: Path, *, experiment_id: str = "", **kwargs: object
) -> AgentConfig:
    experiment_dir = project_dir / "experiments" / experiment_id
    return AgentConfig(
        name="evaluator",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "evaluator_system.md",
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
        max_turns=10,
        cwd=project_dir,
    )
