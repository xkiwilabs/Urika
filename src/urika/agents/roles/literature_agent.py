"""Literature agent — ingests and searches project knowledge."""

from __future__ import annotations

from pathlib import Path

from urika.agents.config import AgentConfig, AgentRole, SecurityPolicy
from urika.agents.prompt import load_prompt

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_role() -> AgentRole:
    return AgentRole(
        name="literature_agent",
        description="Ingests and searches project knowledge and literature",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    knowledge_dir = project_dir / "knowledge"
    return AgentConfig(
        name="literature_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "literature_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "knowledge_dir": str(knowledge_dir),
            },
        ),
        allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[knowledge_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=15,
        cwd=project_dir,
    )
