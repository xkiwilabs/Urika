"""Memory curator agent — proposes merge/archive/flag decisions on project memory.

The curator is an **emit-only** role: given the current contents of the
project's memory directory (handed to it via the per-turn user message),
it returns a single JSON object describing proposed changes. It has no
filesystem access — apply logic lives in T2.6 of the v0.5.0 memory-
deepening plan, gated on user review.
"""

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
        name="memory_curator",
        description=(
            "Proposes merge / archive / flag decisions on the project's "
            "memory directory (emit-only, no filesystem access)"
        ),
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    """Build the curator's runtime configuration.

    The curator receives memory contents through the per-turn user
    message (built by the dispatch logic in T2.5) and emits a single
    JSON object. It therefore needs **no** tool access — granting
    Read/Glob/Grep would let it browse beyond the curated context, and
    granting Write would let it skip the user-review gate. Belt and
    braces: ``allowed_tools=[]`` AND an empty ``SecurityPolicy``.
    """
    runtime_config = load_runtime_config(project_dir)
    return AgentConfig(
        name="memory_curator",
        system_prompt=load_prompt(_PROMPTS_DIR / "memory_curator_system.md"),
        allowed_tools=[],
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[],
            readable_dirs=[],
            allowed_bash_prefixes=[],
            blocked_bash_patterns=[],
        ),
        max_turns=3,
        cwd=project_dir,
        model=get_agent_model("memory_curator", runtime_config),
        env=build_agent_env_for_endpoint(project_dir, "memory_curator", runtime_config),
    )
