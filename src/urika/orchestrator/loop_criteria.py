"""Criteria and result-checking helpers for the orchestrator loop.

Split out of loop.py as part of Phase 8 refactoring. These are the
small, reusable pieces the main loop uses to decide: "did this agent
call succeed, which metric is the headline, and if it failed, should
we pause or fail the session?"

Constants:
    _LOWER_IS_BETTER      — metric names where lower values are preferred
                             (errors, losses, p-values). Shared with the
                             display module.
    _PAUSABLE_ERRORS      — error categories that pause the session
                             (transient: rate_limit, billing) rather than
                             failing it.

Functions:
    _check_result         — inspect an AgentResult; pause / fail the
                             session on failure; return error string or None.
    _detect_primary_metric — choose the headline metric from a dict.
    _noop_callback        — default no-op progress callback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from urika.agents.runner import AgentResult
from urika.core.session import fail_session, pause_session

logger = logging.getLogger(__name__)

# Categories that should pause instead of fail — the experiment can
# be resumed once the transient issue resolves.
_PAUSABLE_ERRORS = frozenset({"rate_limit", "billing"})

# Metrics where lower values are better (errors, losses, p-values).
# Shared with loop_display._print_run_summary so the "best" calculation
# matches the primary-metric direction detection.
_LOWER_IS_BETTER = {
    "rmse", "mse", "mae", "mape", "loss", "error",
    "brier_score", "log_loss", "sse", "residual",
    "p_value", "aic", "bic", "deviance", "perplexity",
}


def _check_result(
    result: AgentResult,
    agent_label: str,
    project_dir: Path,
    experiment_id: str,
    progress: Callable[..., Any],
) -> str | None:
    """Check an agent result. Returns None if OK, or an error string.

    On rate-limit or billing errors the session is **paused** (not
    failed) so it can be resumed later. On auth errors or unknown
    failures the session is failed. The progress callback receives a
    human-readable message in all cases.
    """
    if result.success:
        return None

    error_msg = result.error or f"{agent_label} failed"
    category = getattr(result, "error_category", "") or ""

    if category in _PAUSABLE_ERRORS:
        # Pause instead of fail — experiment can be resumed.
        progress("result", error_msg)
        try:
            pause_session(project_dir, experiment_id)
        except Exception:
            pass
        return error_msg

    # Auth or unknown errors — fail the session.
    progress("result", error_msg)
    try:
        fail_session(project_dir, experiment_id, error=error_msg)
    except Exception:
        pass
    return error_msg


def _detect_primary_metric(
    metrics: dict[str, float],
) -> tuple[str, str]:
    """Detect the primary metric and its direction from a metrics dict.

    Returns (metric_name, direction) where direction is
    'higher_is_better' or 'lower_is_better'. Prefers common metrics
    in this order: r2, accuracy, f1, rmse, mae, then the first numeric key.
    """
    preferred = ["r2", "accuracy", "f1", "rmse", "mae", "mse", "loss"]
    for name in preferred:
        if name in metrics and isinstance(metrics[name], (int, float)):
            direction = (
                "lower_is_better" if name in _LOWER_IS_BETTER else "higher_is_better"
            )
            return name, direction
    # Fallback: first numeric metric
    for name, val in metrics.items():
        if isinstance(val, (int, float)):
            direction = (
                "lower_is_better" if name in _LOWER_IS_BETTER else "higher_is_better"
            )
            return name, direction
    return "", "higher_is_better"


def _noop_callback(event: str, detail: str = "") -> None:
    """Default no-op progress callback."""
