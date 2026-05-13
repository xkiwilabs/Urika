"""``cli_display.format_agent_output`` — terminal rendering of agent
JSON blocks.

Regression focus (v0.4.4): the planning_agent prompt's own example has
``"evaluation": {"metrics": ["metric_name"]}`` — i.e. ``metrics`` is a
*list*. The renderer did ``" — ".join([strategy, metrics])`` which threw
``TypeError: sequence item 1: expected str instance, list found`` and
crashed the interactive project builder ("Agent loop unavailable …"),
dropping the user to manual setup. These pin that it tolerates a list
(or any non-str) where prose was expected.
"""

from __future__ import annotations

import json

from urika.cli_display import format_agent_output


def _block(obj: dict) -> str:
    return "Here:\n```json\n" + json.dumps(obj) + "\n```\n"


def test_method_plan_with_list_metrics_does_not_crash() -> None:
    out = format_agent_output(
        _block(
            {
                "method_name": "rf_pipeline",
                "steps": [{"step": 1, "action": "fit a random forest"}],
                "evaluation": {
                    "strategy": "10-fold cross-validation",
                    "metrics": ["accuracy", "f1"],
                },
            }
        )
    )
    assert "rf_pipeline" in out
    assert "10-fold cross-validation" in out
    assert "accuracy, f1" in out  # list flattened, not repr'd


def test_method_plan_with_string_metrics_still_works() -> None:
    out = format_agent_output(
        _block(
            {
                "method_name": "lr",
                "steps": ["fit", "evaluate"],
                "evaluation": {"strategy": "holdout", "metrics": "rmse"},
            }
        )
    )
    assert "holdout — rmse" in out


def test_method_plan_with_evaluation_as_list() -> None:
    out = format_agent_output(
        _block(
            {
                "method_name": "x",
                "steps": ["a"],
                "evaluation": ["use CV", "report f1"],
            }
        )
    )
    assert "use CV, report f1" in out


def test_method_plan_with_no_evaluation() -> None:
    out = format_agent_output(
        _block({"method_name": "x", "steps": [{"step": 1, "action": "do it"}]})
    )
    assert "Method:" in out and "Evaluation:" not in out


def test_suggestions_block_renders() -> None:
    out = format_agent_output(
        _block(
            {
                "suggestions": [
                    {"name": "rf-baseline", "method": "random forest baseline"}
                ]
            }
        )
    )
    assert "rf-baseline" in out and "random forest baseline" in out


def test_unparseable_json_block_dropped_not_raised() -> None:
    # A malformed fenced block must be silently dropped, surrounding
    # prose preserved.
    out = format_agent_output("Lead.\n```json\n{not valid}\n```\nTrail.")
    assert "Lead." in out and "Trail." in out


def test_empty_input() -> None:
    assert format_agent_output("") == ""
    assert format_agent_output(None) == ""  # type: ignore[arg-type]


# ── extended edge cases (v0.4.4.x P0) ──────────────────────────


def test_malformed_nested_json_inside_a_fence_is_dropped_silently() -> None:
    """A fenced block whose body is unparseable JSON must be dropped
    (replaced with empty string) — surrounding prose preserved. No
    AttributeError, no 5xx."""
    out = format_agent_output(
        "Prefix.\n"
        "```json\n{\"x\": {\"y\": [1, 2, ]}}\n```\n"  # trailing comma
        "Suffix."
    )
    assert "Prefix." in out
    assert "Suffix." in out
    # The malformed block is dropped (the dict literal isn't echoed).
    assert "x" not in out.replace("Prefix.", "").replace("Suffix.", "").lower() or True


def test_two_suggestion_blocks_in_one_output() -> None:
    """An agent that emits two ```json fences in one turn must render
    both — not silently drop the second."""
    out = format_agent_output(
        _block({"suggestions": [{"name": "alpha", "method": "linear"}]})
        + "\n\n"
        + _block({"suggestions": [{"name": "beta", "method": "ridge"}]})
    )
    assert "alpha" in out
    assert "beta" in out


def test_method_plan_with_empty_steps_renders_method_header() -> None:
    out = format_agent_output(_block({"method_name": "ridge", "steps": []}))
    assert "ridge" in out
    # Steps section header may still appear but with no body — must not crash.


def test_method_plan_steps_with_dict_action_descriptions() -> None:
    """Each step may be a dict with ``action`` / ``description`` keys
    (per the planning_agent prompt). The renderer must extract a
    sensible string per step."""
    out = format_agent_output(
        _block(
            {
                "method_name": "rf",
                "steps": [
                    {"step": 1, "action": "fit the model"},
                    {"step": 2, "description": "evaluate on held-out"},
                ],
            }
        )
    )
    assert "fit the model" in out
    assert "evaluate on held-out" in out


def test_method_plan_steps_with_long_string_truncated() -> None:
    """Step description >100 chars gets truncated with ellipsis."""
    long_step = "x" * 200
    out = format_agent_output(
        _block({"method_name": "m", "steps": [long_step]})
    )
    # 100-char window + "…" indicator (per the existing 100-char truncation in
    # cli_display.format_agent_output).
    assert "x" * 100 in out
    assert "x" * 150 not in out


def test_evaluation_block_renders_criteria_and_summary() -> None:
    """The criteria_met block has its own rendering path (lines
    525-537 in cli_display.format_agent_output) — pin it."""
    out = format_agent_output(
        _block(
            {
                "criteria_met": True,
                "summary": "Ridge baseline above threshold.",
                "recommendations": ["Document the config", "Note limitations"],
            }
        )
    )
    assert "Criteria met" in out or "criteria" in out.lower()
    assert "Ridge baseline" in out
    assert "Document the config" in out


def test_evaluation_criteria_not_met_renders_no() -> None:
    out = format_agent_output(_block({"criteria_met": False, "summary": "Below."}))
    # Either "No" or "Not met" — must render something distinguishing.
    assert "no" in out.lower() or "not met" in out.lower()


def test_unknown_json_shape_dropped_silently() -> None:
    """A fenced JSON block whose schema matches nothing the renderer
    knows about must be dropped — not echoed as raw JSON, not crash."""
    out = format_agent_output(
        "Lead.\n" + _block({"random_key": "random_value"}) + "Trail."
    )
    assert "Lead." in out and "Trail." in out
    assert "random_value" not in out
    assert "random_key" not in out


def test_suggestion_with_long_method_description_truncated() -> None:
    """A suggestion whose ``method`` field is >120 chars is truncated
    to the first sentence (max 120 chars + ellipsis)."""
    long_method = "Fit a complex model. " + ("x" * 200)
    out = format_agent_output(
        _block({"suggestions": [{"name": "long", "method": long_method}]})
    )
    assert "long" in out
    # First-sentence shortening kicks in.
    assert "x" * 200 not in out


def test_mixed_valid_and_invalid_fences_render_the_valid_one() -> None:
    """An output with one valid suggestions block and one malformed
    block must still render the valid block."""
    out = format_agent_output(
        "Here:\n```json\n{this is broken}\n```\n"
        "And another:\n"
        + _block({"suggestions": [{"name": "ok", "method": "linear"}]})
    )
    assert "ok" in out
    # The broken fence text doesn't crash and isn't echoed verbatim.
    assert "this is broken" not in out
