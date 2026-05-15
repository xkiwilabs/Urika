"""Literature agent — ingests and searches project knowledge."""

from __future__ import annotations

import tomllib
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


def _is_web_search_enabled(project_dir: Path) -> bool:
    """Check if web search is enabled in the project's urika.toml."""
    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return False
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return bool(data.get("preferences", {}).get("web_search", False))
    except Exception:
        return False


def get_role() -> AgentRole:
    return AgentRole(
        name="literature_agent",
        description="Ingests and searches project knowledge and literature",
        build_config=build_config,
    )


def build_config(project_dir: Path, **kwargs: object) -> AgentConfig:
    runtime_config = load_runtime_config(project_dir)
    knowledge_dir = project_dir / "knowledge"
    # Web search requires cloud access — disable for private projects
    web_search_enabled = (
        _is_web_search_enabled(project_dir) and runtime_config.privacy_mode != "private"
    )

    allowed_tools = ["Read", "Write", "Bash", "Glob", "Grep"]
    if web_search_enabled:
        allowed_tools.append("WebSearch")

    web_search_section = ""
    if web_search_enabled:
        web_search_section = (
            "\n## Web Search\n\n"
            "You have access to the **WebSearch** tool to find relevant academic "
            "papers, methods, and prior work.\n\n"
            "### Guidelines\n\n"
            "- Search for whether proposed methods have been used for this kind "
            "of research before\n"
            "- Look for relevant papers, established methods, and prior work in "
            "the domain\n"
            "- Summarize findings before ingesting — do not flood with papers "
            "(max 3-5 per search)\n"
            "- Always include citation information (authors, year, title) in "
            "your findings\n"
            "- Prefer recent, high-impact papers from reputable journals\n"
            "- Cross-reference search results with existing knowledge before "
            "adding duplicates\n"
        )

    return AgentConfig(
        name="literature_agent",
        system_prompt=load_prompt(
            _PROMPTS_DIR / "literature_agent_system.md",
            variables={
                "project_dir": str(project_dir),
                "knowledge_dir": str(knowledge_dir),
                "web_search_section": web_search_section,
            },
        ),
        allowed_tools=allowed_tools,
        disallowed_tools=[],
        security=SecurityPolicy(
            writable_dirs=[knowledge_dir],
            readable_dirs=[project_dir],
            allowed_bash_prefixes=["python ", "pip "],
            blocked_bash_patterns=["rm -rf", "git push", "git reset"],
        ),
        max_turns=15,
        cwd=project_dir,
        model=get_agent_model("literature_agent", runtime_config),
        env=build_agent_env_for_endpoint(
            project_dir, "literature_agent", runtime_config
        ),
    )
