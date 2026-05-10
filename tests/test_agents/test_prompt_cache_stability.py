"""Verify the v0.4.3 Tier-1 prompt cache-reuse reorder works.

For each agent role, render the system prompt twice with different
``experiment_id`` / ``experiment_dir`` values (same project), then
measure the longest common byte prefix. After the Tier-1 reorder the
prefix should be the vast majority of the prompt, since the only
varying content is now in the trailing ``Experiment Context`` block.

This is the structural check Anthropic prompt caching hinges on:
the cached chunk is the LONGEST common prefix between two requests.
A high common-prefix ratio means the next experiment's first turn
will hit the cache (within the 5min TTL) instead of paying full
creation cost. Pre-reorder the prefix was ~0 bytes because
``{experiment_id}`` and ``{experiment_dir}`` were at lines 5-7.

Catches the regression "someone added ``{experiment_dir}/foo`` mid-
body again" — the prefix would shrink and the threshold would fail.

Hermetic: no disk writes, no API calls, sub-second runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.registry import AgentRegistry


# Roles that take per-experiment context. Other roles
# (data_agent, tool_builder, literature_agent, project_summarizer,
# project_builder, echo, finalizer, project_summarizer) don't take
# experiment_id at all and are excluded.
_PER_EXPERIMENT_ROLES = [
    "task_agent",
    "evaluator",
    "advisor_agent",
    "planning_agent",
    "report_agent",
    "presentation_agent",
]

# Minimum prefix-share threshold. A reorder regression that re-
# introduces a path interpolation in the body would drop the prefix
# below this.
_MIN_PREFIX_RATIO = 0.90


@pytest.fixture
def project_with_two_experiments(tmp_path):
    """Build a minimal project workspace with two experiment IDs.

    Two real directories so the role builders' ``experiment_dir``
    paths resolve to existing locations. No actual experiment data
    needed — we only render the system prompt, never invoke an
    agent.
    """
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "alpha"
    config = ProjectConfig(
        name="alpha",
        question="Does X predict Y?",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(proj, config)

    exp1 = "exp-001-baseline"
    exp2 = "exp-002-followup"
    (proj / "experiments" / exp1).mkdir(parents=True)
    (proj / "experiments" / exp2).mkdir(parents=True)
    return proj, exp1, exp2


def _common_prefix_len(a: str, b: str) -> int:
    """Return the length of the longest common byte prefix."""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def _render(role_name: str, project_dir: Path, experiment_id: str) -> str:
    registry = AgentRegistry()
    registry.discover()
    role = registry.get(role_name)
    assert role is not None, f"Role {role_name!r} not found in registry"
    config = role.build_config(
        project_dir=project_dir, experiment_id=experiment_id
    )
    return config.system_prompt


@pytest.mark.parametrize("role_name", _PER_EXPERIMENT_ROLES)
def test_prompt_prefix_stable_across_experiments(
    role_name, project_with_two_experiments
) -> None:
    """The system prompt must share >=90% of its bytes with the
    next experiment's prompt. Anything less means the Tier-1
    reorder leaked a per-experiment variable into the body again."""
    proj, exp1, exp2 = project_with_two_experiments

    p1 = _render(role_name, proj, exp1)
    p2 = _render(role_name, proj, exp2)

    assert p1 != p2, (
        f"{role_name}: prompts for two different experiments are "
        f"byte-identical — likely the experiment_id placeholder "
        f"isn't being substituted at all"
    )

    prefix = _common_prefix_len(p1, p2)
    total = max(len(p1), len(p2))
    ratio = prefix / total if total else 0.0

    # Diagnostic message includes the first-divergence byte snippet
    # so a future regression report shows what leaked into the body.
    diverge_at = prefix
    snippet_a = p1[diverge_at : diverge_at + 80].replace("\n", "\\n")
    snippet_b = p2[diverge_at : diverge_at + 80].replace("\n", "\\n")
    assert ratio >= _MIN_PREFIX_RATIO, (
        f"{role_name}: cached prefix is only {ratio:.1%} of total "
        f"({prefix} / {total} bytes) — Tier-1 reorder regression. "
        f"First divergence at byte {diverge_at}:\n"
        f"  exp1: {snippet_a!r}\n"
        f"  exp2: {snippet_b!r}"
    )


def test_orchestrator_prefix_also_stable(project_with_two_experiments) -> None:
    """Orchestrator is structurally different from per-experiment
    roles (chat-style with ``current_state`` etc.) so it has its
    own builder. Verify its experiment_id move worked too."""
    proj, exp1, exp2 = project_with_two_experiments

    # Orchestrator chat is not in the agent registry — it has its
    # own loader. Check its prompt directly.
    from urika.agents.prompt import load_prompt

    prompts_dir = (
        Path(__file__).parent.parent.parent
        / "src" / "urika" / "agents" / "roles" / "prompts"
    )
    template = prompts_dir / "orchestrator_system.md"

    common_vars = {
        "current_state": "project loaded",
        "project_name": "alpha",
        "question": "Does X predict Y?",
        "mode": "exploratory",
        "data_dir": str(proj / "data"),
    }
    p1 = load_prompt(template, variables={**common_vars, "experiment_id": exp1})
    p2 = load_prompt(template, variables={**common_vars, "experiment_id": exp2})

    assert p1 != p2

    prefix = _common_prefix_len(p1, p2)
    total = max(len(p1), len(p2))
    ratio = prefix / total

    assert ratio >= _MIN_PREFIX_RATIO, (
        f"orchestrator: cached prefix is only {ratio:.1%} "
        f"({prefix} / {total} bytes) — experiment_id leaked back "
        f"into the body"
    )


def test_full_byte_identity_within_one_experiment(project_with_two_experiments) -> None:
    """As a sanity check: rendering the SAME (project, experiment)
    twice should give a byte-identical prompt. If this ever fails,
    something non-deterministic snuck into the prompt rendering
    (e.g. a timestamp or PID) and within-experiment caching is
    broken."""
    proj, exp1, _ = project_with_two_experiments

    for role_name in _PER_EXPERIMENT_ROLES:
        p_a = _render(role_name, proj, exp1)
        p_b = _render(role_name, proj, exp1)
        assert p_a == p_b, (
            f"{role_name}: rendering the SAME (project, experiment) "
            f"twice produced different bytes — non-determinism in "
            f"the prompt builder. Within-experiment caching will "
            f"break."
        )


def test_planning_agent_system_prompt_byte_stable_across_memory_changes(
    project_with_two_experiments, monkeypatch
) -> None:
    """Regression: planning_agent's system prompt must be byte-
    identical across builds even when project memory + advisor
    context summary change between calls.

    Pre-this-fix planning_agent.py:53-63 *prepended* both blocks to
    the system prompt. Any change — adding a memory entry, the
    advisor producing a new summary — busted the cached prefix for
    the entire 5.9KB base prompt. After v0.4.3 audit rec #2, both
    flow via the per-turn user message instead, leaving the system
    prompt cacheable across sessions.

    The test seeds a project memory file, builds the planning_agent
    config, then ADDS another memory entry and rebuilds. The two
    system prompts must be byte-identical. (User-message context
    is a separate concern; this test only covers the system-prompt
    invariant the cache hinges on.)
    """
    from urika.core.project_memory import save_entry

    proj, exp1, _ = project_with_two_experiments

    # First build with no memory entries.
    p_before = _render("planning_agent", proj, exp1)

    # Add a memory entry and rebuild.
    save_entry(
        proj,
        mem_type="user",
        body="The user prefers tree-based models for tabular data.",
        description="prefers tree-based models",
    )
    p_after = _render("planning_agent", proj, exp1)

    assert p_before == p_after, (
        "planning_agent system prompt changed when project memory was "
        "added — memory must flow via the user message, not the system "
        "prompt, so the cache prefix stays stable across sessions"
    )


def test_planning_context_helper_includes_memory(
    project_with_two_experiments,
) -> None:
    """The complement of the test above: ``format_planning_context``
    DOES surface memory + summary content. Together these prove the
    refactor moved the content rather than dropping it."""
    from urika.agents.roles.planning_agent import format_planning_context
    from urika.core.project_memory import save_entry

    proj, _, _ = project_with_two_experiments

    # Empty before any memory.
    assert format_planning_context(proj) == ""

    # After adding memory, it shows up in the context block.
    save_entry(
        proj,
        mem_type="user",
        body="Use only methods that produce diagnostic plots.",
        description="diagnostic plots required",
    )
    ctx = format_planning_context(proj)
    assert "Project Memory & Prior Context" in ctx
    assert "diagnostic plots" in ctx


def test_prefix_ratios_summary(project_with_two_experiments, capsys) -> None:
    """Print a summary table of cache-prefix ratios for visibility.

    Doesn't assert; ``-s`` flag shows the numbers when running
    pytest manually. Useful for tracking the prompt cache health
    over time and for the cache-reuse plan doc.
    """
    proj, exp1, exp2 = project_with_two_experiments

    print()
    print(f"{'role':<24} {'total':>8} {'prefix':>8} {'ratio':>8}")
    print("-" * 52)
    for role_name in _PER_EXPERIMENT_ROLES:
        p1 = _render(role_name, proj, exp1)
        p2 = _render(role_name, proj, exp2)
        prefix = _common_prefix_len(p1, p2)
        total = max(len(p1), len(p2))
        ratio = prefix / total if total else 0.0
        print(f"{role_name:<24} {total:>8} {prefix:>8} {ratio:>7.1%}")
