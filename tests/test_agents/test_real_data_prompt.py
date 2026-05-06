"""Tests for v0.4.2 H-bug-2 prompt-level fix: real-data-only language.

Pre-v0.4.2 the task_agent and data_agent prompts had ZERO guardrails
against simulating, fabricating, or substituting placeholder data.
Under turn/budget pressure the agent could rationalize "the real run
would take too long, let me synthesize a small example" and produce
runs whose metrics were scientifically meaningless.

These tests pin the prohibition language so a future prompt edit
that accidentally drops it surfaces as a test failure rather than a
silent regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROMPTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "urika" / "agents" / "roles" / "prompts"
)


@pytest.fixture
def task_agent_prompt() -> str:
    return (PROMPTS_DIR / "task_agent_system.md").read_text(encoding="utf-8")


@pytest.fixture
def data_agent_prompt() -> str:
    return (PROMPTS_DIR / "data_agent_system.md").read_text(encoding="utf-8")


class TestTaskAgentForbidsSyntheticData:
    def test_has_real_data_only_section(self, task_agent_prompt: str) -> None:
        assert "Real Data Only" in task_agent_prompt
        assert "NEVER simulate" in task_agent_prompt
        # The "no exceptions" framing is load-bearing — softening it
        # invites the agent to negotiate around the rule.
        assert "no exceptions" in task_agent_prompt.lower()

    def test_lists_canonical_forbidden_calls(
        self, task_agent_prompt: str
    ) -> None:
        # If any of these gets dropped, the agent has more wiggle room.
        for forbidden in (
            "make_classification",
            "make_regression",
            "make_blobs",
            "np.random.normal",
            "simulate_",
        ):
            assert forbidden in task_agent_prompt, (
                f"Forbidden-pattern example {forbidden!r} missing from "
                f"task_agent_system.md — the agent may not recognize "
                f"it as off-limits."
            )

    def test_documents_legitimate_uses_of_randomness(
        self, task_agent_prompt: str
    ) -> None:
        """Without the 'allowed uses' carve-out the agent could
        over-correct and refuse legitimate train/test shuffling."""
        assert "Allowed uses of randomness" in task_agent_prompt
        # The shuffling and bootstrap exceptions must survive.
        assert "Train/test split" in task_agent_prompt
        assert "Bootstrap" in task_agent_prompt

    def test_directs_agent_to_stop_when_data_unreadable(
        self, task_agent_prompt: str
    ) -> None:
        """The fallback when data truly can't be loaded must be 'stop
        and report' — not 'substitute synthetic'."""
        assert "STOP" in task_agent_prompt
        # The phrase that closes the escape hatch.
        assert (
            "Do NOT substitute synthetic data" in task_agent_prompt
            or "do not substitute synthetic" in task_agent_prompt.lower()
        )


class TestDataAgentForbidsSyntheticData:
    def test_has_real_data_only_section(self, data_agent_prompt: str) -> None:
        assert "Real Data Only" in data_agent_prompt
        assert "NEVER" in data_agent_prompt
        assert "synthesize" in data_agent_prompt or "simulate" in data_agent_prompt

    def test_directs_to_report_error_on_unreadable(
        self, data_agent_prompt: str
    ) -> None:
        assert (
            "report the error" in data_agent_prompt.lower()
            or "stop" in data_agent_prompt.lower()
        )
