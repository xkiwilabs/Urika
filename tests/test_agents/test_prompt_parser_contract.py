"""Prompt ↔ parser contract tests.

The orchestrator parsers (``urika.orchestrator.parsing``) expect agents
to emit JSON blocks with specific keys. The role *prompts* tell the
agents what to emit, via a ```` ```json ```` example block. If those two
ever drift apart — someone edits ``task_agent_system.md`` to rename
``run_id`` → ``id``, say — every real run silently records 0 runs and
every experiment fails, and (pre-v0.4.4) not one unit test went red,
because the canned outputs in ``test_loop.py`` are hand-written to match
the parsers rather than extracted from the prompts.

These tests extract the example JSON block from each role's prompt and
assert the matching parser accepts it. ~free to run, and they fail the
moment the prompt's documented output schema stops matching the code
that consumes it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from urika.orchestrator.parsing import (
    parse_evaluation,
    parse_method_plan,
    parse_run_records,
    parse_suggestions,
)

_PROMPTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "urika"
    / "agents"
    / "roles"
    / "prompts"
)


def _rendered_prompt(role: str) -> str:
    """Return the role's system prompt as the agent actually sees it.

    Prompt files use ``str.format_map`` semantics: ``{{`` / ``}}`` are
    literal braces, ``{name}`` are substitutions. We don't care about
    the substitutions here, so just collapse the escaped braces.
    """
    raw = (_PROMPTS_DIR / f"{role}_system.md").read_text(encoding="utf-8")
    return raw.replace("{{", "{").replace("}}", "}")


def _first_json_block(text: str) -> dict:
    """Parse the first ```` ```json ```` fenced block in ``text``.

    Uses the same relaxed fence regex as
    ``parsing._extract_json_blocks`` so we're testing the real contract.
    """
    m = re.search(r"```(?:json|JSON)\s*(.*?)```", text, re.DOTALL)
    assert m is not None, "no ```json example block found in prompt"
    return json.loads(m.group(1).strip())


def test_task_agent_run_record_example_parses() -> None:
    prompt = _rendered_prompt("task_agent")
    # The example must be a valid JSON object on its own ...
    example = _first_json_block(prompt)
    assert {"run_id", "method", "metrics"} <= example.keys(), (
        "task_agent prompt's run-record example is missing a key "
        "parse_run_records requires"
    )
    # ... and the orchestrator parser must accept the prompt text and
    # yield exactly one RunRecord from it.
    records = parse_run_records(prompt)
    assert len(records) >= 1, (
        "parse_run_records found 0 records in the task_agent prompt — "
        "the run-record schema in the prompt and the parser have drifted"
    )
    r = records[0]
    assert r.run_id and r.method
    assert isinstance(r.metrics, dict)
    assert isinstance(r.params, dict)


def test_evaluator_example_parses() -> None:
    prompt = _rendered_prompt("evaluator")
    example = _first_json_block(prompt)
    assert "criteria_met" in example
    parsed = parse_evaluation(prompt)
    assert parsed is not None, (
        "parse_evaluation found no criteria_met block in the evaluator "
        "prompt — schema drift"
    )
    assert "criteria_met" in parsed


def test_advisor_example_parses() -> None:
    prompt = _rendered_prompt("advisor_agent")
    example = _first_json_block(prompt)
    assert "suggestions" in example
    parsed = parse_suggestions(prompt)
    assert parsed is not None, (
        "parse_suggestions found no suggestions block in the advisor "
        "prompt — schema drift"
    )
    sugg = parsed.get("suggestions")
    assert isinstance(sugg, list) and len(sugg) >= 1
    # The meta loop reads ``name`` and ``method`` off the first suggestion.
    assert "name" in sugg[0]
    assert "method" in sugg[0]


def test_planning_agent_example_parses() -> None:
    prompt = _rendered_prompt("planning_agent")
    example = _first_json_block(prompt)
    assert "method_name" in example and "steps" in example
    parsed = parse_method_plan(prompt)
    assert parsed is not None, (
        "parse_method_plan found no method_name+steps block in the "
        "planning_agent prompt — schema drift"
    )
    assert "method_name" in parsed and "steps" in parsed


@pytest.mark.parametrize(
    "role",
    ["task_agent", "evaluator", "advisor_agent", "planning_agent"],
)
def test_prompt_json_example_is_valid_json(role: str) -> None:
    """A malformed example block in a prompt is itself a bug — the agent
    is being shown invalid JSON to copy."""
    _first_json_block(_rendered_prompt(role))
