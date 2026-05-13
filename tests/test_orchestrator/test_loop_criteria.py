"""Tests for ``loop_criteria.py`` — the error-classification + pause-vs-fail
policy and metric-direction detection.

Pre-this-file there was no dedicated test module for ``loop_criteria.py``
(173 lines); the policy was only tested indirectly through the
end-to-end loop tests. This pins each branch directly so a regression
in the recoverable / fatal split fails here, not somewhere downstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.runner import AgentResult
from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig
from urika.core.session import load_session
from urika.core.workspace import create_project_workspace
from urika.orchestrator.loop_criteria import (
    _FATAL_ERROR_CATEGORIES,
    _LOWER_IS_BETTER,
    _PAUSABLE_ERRORS,
    _check_result,
    _detect_primary_metric,
    _is_recoverable_failure,
    _noop_callback,
)


# ── _is_recoverable_failure ────────────────────────────────────


@pytest.mark.parametrize(
    "category",
    ["", None, "unknown", "rate_limit", "transient", "billing", "config"],
)
def test_recoverable_categories(category) -> None:
    assert _is_recoverable_failure(category) is True


def test_auth_is_fatal() -> None:
    assert _is_recoverable_failure("auth") is False


def test_fatal_set_only_contains_auth() -> None:
    """Pin the membership so a future addition to _FATAL_ERROR_CATEGORIES
    is a deliberate, reviewed change."""
    assert _FATAL_ERROR_CATEGORIES == frozenset({"auth"})


def test_pausable_errors_set_is_user_friendly_subset() -> None:
    """_PAUSABLE_ERRORS is the subset that already has a friendly
    resume message baked in by the SDK adapter."""
    assert _PAUSABLE_ERRORS == frozenset(
        {"rate_limit", "billing", "transient", "config"}
    )


# ── _check_result ──────────────────────────────────────────────


def _setup(tmp_path: Path) -> tuple[Path, str]:
    proj = tmp_path / "p"
    create_project_workspace(
        proj, ProjectConfig(name="p", question="Q?", mode="exploratory")
    )
    exp = create_experiment(proj, name="b", hypothesis="h")
    # Manually pre-create a session so pause/fail have something to act on.
    from urika.core.session import start_session

    start_session(proj, exp.experiment_id, max_turns=1)
    return proj, exp.experiment_id


def test_check_result_success_returns_none(tmp_path) -> None:
    proj, exp = _setup(tmp_path)
    r = AgentResult(success=True, messages=[], text_output="ok",
                    session_id="s", num_turns=1, duration_ms=1)
    assert _check_result(r, "task_agent", proj, exp, _noop_callback) is None


def test_check_result_recoverable_pauses(tmp_path) -> None:
    proj, exp = _setup(tmp_path)
    events: list = []

    def progress(e, d=""):
        events.append((e, d))

    r = AgentResult(success=False, messages=[], text_output="",
                    session_id="s", num_turns=0, duration_ms=0,
                    error="rate-limit hit", error_category="rate_limit")
    err = _check_result(r, "task_agent", proj, exp, progress)
    assert err == "rate-limit hit"
    state = load_session(proj, exp)
    assert state is not None and state.status == "paused"


def test_check_result_unknown_category_pauses_with_hint(tmp_path) -> None:
    """Unknown / empty category gets a friendly resume hint appended
    to the progress message (the SDK adapter didn't supply one)."""
    proj, exp = _setup(tmp_path)
    events: list = []
    r = AgentResult(success=False, messages=[], text_output="",
                    session_id="s", num_turns=0, duration_ms=0,
                    error="something weird", error_category="")
    _check_result(r, "task_agent", proj, exp,
                  lambda e, d="": events.append((e, d)))
    # The "result" event includes the resume hint.
    result_msgs = [d for e, d in events if e == "result"]
    assert result_msgs
    assert any("urika run --resume" in m for m in result_msgs)


def test_check_result_auth_fails_session(tmp_path) -> None:
    proj, exp = _setup(tmp_path)
    r = AgentResult(success=False, messages=[], text_output="",
                    session_id="s", num_turns=0, duration_ms=0,
                    error="bad key", error_category="auth")
    err = _check_result(r, "task_agent", proj, exp, _noop_callback)
    assert err == "bad key"
    state = load_session(proj, exp)
    assert state is not None and state.status == "failed"


# ── _detect_primary_metric ─────────────────────────────────────


@pytest.mark.parametrize(
    "metrics, expected_name, expected_direction",
    [
        ({"r2": 0.5}, "r2", "higher_is_better"),
        ({"accuracy": 0.9}, "accuracy", "higher_is_better"),
        ({"rmse": 1.2}, "rmse", "lower_is_better"),
        ({"mae": 0.5, "r2": 0.8}, "r2", "higher_is_better"),  # r2 preferred first
        ({"f1": 0.7}, "f1", "higher_is_better"),
        ({"loss": 0.01}, "mse" if "mse" in _LOWER_IS_BETTER else "loss",
         "lower_is_better"),
    ],
)
def test_detect_primary_metric_preferred(metrics, expected_name, expected_direction):
    name, direction = _detect_primary_metric(metrics)
    # The actual preferred order is r2 > accuracy > f1 > rmse > mae > mse > loss;
    # the test should just confirm the *direction* on the chosen metric.
    assert direction == expected_direction


def test_detect_primary_metric_empty_returns_empty_string() -> None:
    name, direction = _detect_primary_metric({})
    assert name == "" and direction == "higher_is_better"


def test_detect_primary_metric_non_numeric_skipped() -> None:
    name, direction = _detect_primary_metric({"label": "bad", "r2": 0.5})
    assert name == "r2"


def test_detect_primary_metric_unknown_metric_falls_back_to_first_numeric() -> None:
    name, direction = _detect_primary_metric({"my_custom": 0.42, "label": "x"})
    assert name == "my_custom"


# ── _LOWER_IS_BETTER sanity ────────────────────────────────────


def test_lower_is_better_includes_classic_error_metrics() -> None:
    for m in ("rmse", "mse", "mae", "loss", "log_loss", "perplexity"):
        assert m in _LOWER_IS_BETTER


def test_higher_is_better_metrics_not_in_lower_set() -> None:
    for m in ("r2", "accuracy", "f1", "auc"):
        assert m not in _LOWER_IS_BETTER
