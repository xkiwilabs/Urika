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

# Categories with a *user-friendly* pause message already supplied by
# the SDK adapter's ``_friendly_error``. Used only to decide whether
# ``_check_result`` should append a generic "resume with …" hint —
# NOT to decide pause-vs-fail (see ``_is_recoverable_failure``).
_PAUSABLE_ERRORS = frozenset(
    {
        "rate_limit",
        "billing",
        # Transient network/server errors (5xx, connection_reset,
        # timeout, bare CLI exit codes with no diagnostic).
        "transient",
        # Configuration errors (MissingPrivateEndpointError,
        # APIKeyRequiredError) — runtime is misconfigured but the
        # experiment state is recoverable.
        "config",
    }
)

# Error categories that genuinely cannot be recovered by resuming —
# the credentials/session themselves are bad, so re-running the same
# turn will hit the same wall. Everything *else* (rate_limit, billing,
# transient, config, and the catch-all "unknown" — which covers
# timeouts, JSON-decode errors inside the SDK, bare "Command failed
# with exit code N", 400s without an auth/billing keyword, etc.) is
# treated as recoverable: the loop **pauses** so ``urika run --resume``
# can retry the turn, instead of hard-failing the whole experiment.
#
# Pre-v0.4.4 only the explicit pausable set above paused; anything
# that fell into "unknown" hard-failed the experiment — frequently on
# turn 1, since the planning agent is the first SDK call every turn.
# A single odd error (a momentary connect blip, an SDK-internal
# decode hiccup) therefore killed multi-hour autonomous runs and left
# brand-new dashboard projects looking broken after one failed run.
_FATAL_ERROR_CATEGORIES = frozenset({"auth"})


def _is_recoverable_failure(category: str | None) -> bool:
    """Return True iff a failed agent result should *pause* (resumable)
    rather than *fail* the session. See ``_FATAL_ERROR_CATEGORIES``."""
    return (category or "") not in _FATAL_ERROR_CATEGORIES

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

    Recoverable failures (everything except ``auth`` —
    see ``_FATAL_ERROR_CATEGORIES``) **pause** the session so a
    ``urika run --resume`` re-runs the turn. Only genuinely
    unrecoverable failures (bad credentials / expired session) **fail**
    the session outright. The progress callback receives a
    human-readable message in all cases.
    """
    if result.success:
        return None

    error_msg = result.error or f"{agent_label} failed"
    category = getattr(result, "error_category", "") or ""

    if _is_recoverable_failure(category):
        # Pause instead of fail — experiment state is intact.
        msg = error_msg
        if category not in _PAUSABLE_ERRORS:
            # Catch-all "unknown" failure — no friendly resume hint was
            # baked in by the adapter, so add one.
            msg = (
                f"{error_msg}\n  The experiment has been paused — "
                "resume with: urika run --resume"
            )
        progress("result", msg)
        try:
            pause_session(project_dir, experiment_id)
        except Exception as exc:
            # Pre-v0.4 this swallowed silently; if session-state
            # persistence fails the run keeps going with a stale
            # session.json. Log so the failure mode is observable.
            logger.warning(
                "pause_session failed during _check_result: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
        return error_msg

    # Unrecoverable (auth) — fail the session.
    progress("result", error_msg)
    try:
        fail_session(project_dir, experiment_id, error=error_msg)
    except Exception as exc:
        logger.warning(
            "fail_session failed during _check_result: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
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
