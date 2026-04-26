"""Regression guard for the system-reminder leakage fix.

Background: the Claude Agent SDK injects system reminders into agent
context (about file safety, malware, tool policies, etc.). Without
explicit guidance, an agent may narrate those reminders in
user-visible prose ("I note the system reminders about malware…"),
which is confusing noise in a research-assistant tool.

Each agent prompt that produces user-visible output now contains an
"Output Hygiene" section instructing the agent to silently follow
those reminders without surfacing them. These tests pin that rule so
a future prompt rewrite can't regress it.

Agents excluded:
- ``echo`` is a test fixture.
- ``orchestrator`` doesn't produce user-visible prose directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROMPTS_DIR = (
    Path(__file__).parent.parent.parent / "src" / "urika" / "agents" / "roles" / "prompts"
)

HYGIENE_AGENTS = [
    "advisor_agent",
    "data_agent",
    "evaluator",
    "finalizer",
    "literature_agent",
    "planning_agent",
    "presentation_agent",
    "project_builder",
    "project_summarizer",
    "report_agent",
    "task_agent",
    "tool_builder",
]


@pytest.mark.parametrize("agent", HYGIENE_AGENTS)
def test_prompt_has_output_hygiene_block(agent: str) -> None:
    text = (PROMPTS_DIR / f"{agent}_system.md").read_text(encoding="utf-8")
    assert "## Output Hygiene" in text, (
        f"{agent} is missing the Output Hygiene section. Without it, the "
        f"agent narrates system reminders in user-visible prose."
    )
    assert "Never narrate, acknowledge, or mention them" in text
