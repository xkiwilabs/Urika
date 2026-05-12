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
