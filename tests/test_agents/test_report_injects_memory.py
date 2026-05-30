"""Report agent read-side memory loop.

The planning and advisor agents already prepend a
``## Project Memory & Prior Context`` block to their per-turn user
message (see ``urika.agents.roles.planning_agent.format_planning_context``
and ``urika.agents.roles.advisor_agent.format_advisor_context``). The
report agent is the project-facing narrative writer — when it produces
the experiment report or the final write-up it MUST also READ the
preferences and decisions that prior sessions captured, so that
audience tone, terminology bans, and any user-pinned framing all
survive into the deliverables.

This test asserts the read-side loop is closed for report_agent: a
parallel ``format_report_context`` helper exists on report_agent, takes
the same single ``project_dir: Path`` argument, and surfaces stored
memory entries under the SAME heading text the planner and advisor use.
"""

from __future__ import annotations

from urika.core import project_memory


def test_report_includes_memory_in_user_message(tmp_path):
    """``format_report_context`` must surface stored project memory under
    the ``Project Memory & Prior Context`` heading — same surface as
    ``format_planning_context`` / ``format_advisor_context`` so a single
    assertion covers all three."""
    proj = tmp_path / "proj"
    (proj / "memory").mkdir(parents=True)
    project_memory.save_entry(
        proj,
        mem_type="user",
        body="user wants reports in terse, bullet-point style",
        description="audience preference",
    )

    from urika.agents.roles import report_agent

    user_message = report_agent.format_report_context(proj)

    assert "Project Memory & Prior Context" in user_message
    assert "terse, bullet-point" in user_message


def test_report_context_empty_when_no_memory(tmp_path):
    """When the project has no memory and no advisor context summary,
    ``format_report_context`` must return an empty string — matches the
    planning / advisor helpers' contract so callers can safely prepend
    the result unconditionally."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)

    from urika.agents.roles import report_agent

    assert report_agent.format_report_context(proj) == ""
