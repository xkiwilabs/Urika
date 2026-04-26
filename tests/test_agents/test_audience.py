"""Tests for audience-mode instruction blocks."""

from __future__ import annotations

import pytest

from urika.agents.audience import AUDIENCE_INSTRUCTIONS, get_audience_instruction


def test_standard_audience_exists_and_is_default():
    assert "standard" in AUDIENCE_INSTRUCTIONS
    assert get_audience_instruction(None) == AUDIENCE_INSTRUCTIONS["standard"]
    assert get_audience_instruction("") == AUDIENCE_INSTRUCTIONS["standard"]


def test_standard_audience_requires_verbose_notes():
    text = AUDIENCE_INSTRUCTIONS["standard"].lower()
    assert "speaker notes" in text
    # standard mode should call out multi-sentence notes
    assert "sentences" in text


def test_expert_audience_is_the_most_concise():
    """Expert assumes shared vocabulary and skips method explanation,
    so its prose is shorter than the audiences that have to walk
    readers through methods. Standard and novice are both deep but
    for different readers (senior undergrad vs no background), so we
    don't pin a strict ordering between those two."""
    assert len(AUDIENCE_INSTRUCTIONS["expert"]) < len(AUDIENCE_INSTRUCTIONS["standard"])
    assert len(AUDIENCE_INSTRUCTIONS["expert"]) < len(AUDIENCE_INSTRUCTIONS["novice"])


@pytest.mark.parametrize("name", ["expert", "standard", "novice"])
def test_get_audience_returns_exact_instruction_for_known_name(name):
    assert get_audience_instruction(name) == AUDIENCE_INSTRUCTIONS[name]


def test_get_audience_falls_back_to_standard_for_unknown_name():
    assert get_audience_instruction("made_up_mode") == AUDIENCE_INSTRUCTIONS["standard"]
