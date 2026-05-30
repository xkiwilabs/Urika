"""Advisor agent read-side memory loop.

The planning agent already prepends a ``## Project Memory & Prior Context``
block to its per-turn user message (see
``urika.agents.roles.planning_agent.format_planning_context``). The advisor
is the strongest source of design rationale captured into project memory,
so it MUST also READ what it (or other agents) wrote in prior sessions.

This test asserts the read-side loop is closed for advisor_agent: a
parallel ``format_advisor_context`` helper exists on advisor_agent, takes
the same single ``project_dir: Path`` argument, returns the SAME
``Project Memory & Prior Context`` heading text, and surfaces stored
memory entries.
"""

from __future__ import annotations

from urika.core import project_memory


def test_advisor_includes_memory_in_user_message(tmp_path):
    """``format_advisor_context`` must surface stored project memory under
    the ``Project Memory & Prior Context`` heading — same surface as
    ``format_planning_context`` so a single assertion covers both."""
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    project_memory.save_entry(
        proj,
        mem_type="user",
        body="user prefers tree-based models for tabular data",
        description="ridge preference",
    )

    from urika.agents.roles import advisor_agent

    user_message = advisor_agent.format_advisor_context(proj)

    assert "Project Memory & Prior Context" in user_message
    assert "tree-based models" in user_message


def test_advisor_context_empty_when_no_memory(tmp_path):
    """When the project has no memory and no advisor context summary,
    ``format_advisor_context`` must return an empty string — matches the
    planning helper's contract so callers can safely prepend the result
    unconditionally."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)

    from urika.agents.roles import advisor_agent

    assert advisor_agent.format_advisor_context(proj) == ""
