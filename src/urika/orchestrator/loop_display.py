"""Console summary rendering for the orchestrator loop.

Split out of loop.py as part of Phase 8 refactoring. One function,
one job: print a human-readable summary of what an experiment turn
produced (runs, methods, best metric, latest observation, next step).

Reuses ``_LOWER_IS_BETTER`` from loop_criteria so the "best" direction
matches primary-metric detection elsewhere.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from urika.core.progress import load_progress
from urika.orchestrator.loop_criteria import _LOWER_IS_BETTER

logger = logging.getLogger(__name__)


def _print_run_summary(
    project_dir: Path,
    experiment_id: str,
    progress: Callable[..., Any],
) -> None:
    """Print a summary of what was achieved in this experiment."""
    try:
        exp_progress = load_progress(project_dir, experiment_id)
        runs = exp_progress.get("runs", [])
        if not runs:
            return

        progress("phase", "")
        progress("phase", "━━━ Run Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Methods tried
        methods = [r["method"] for r in runs]
        progress("result", f"{len(runs)} runs across {len(set(methods))} methods")

        # Best metrics — find the first numeric metric, respecting direction
        best_val = None
        best_method = None
        best_metric_name = None
        lower_is_better = False
        for r in runs:
            for key, val in r.get("metrics", {}).items():
                if isinstance(val, (int, float)):
                    if best_metric_name is None:
                        best_metric_name = key
                        lower_is_better = key in _LOWER_IS_BETTER
                    if key == best_metric_name:
                        if best_val is None:
                            best_val = val
                            best_method = r["method"]
                        elif lower_is_better and val < best_val:
                            best_val = val
                            best_method = r["method"]
                        elif not lower_is_better and val > best_val:
                            best_val = val
                            best_method = r["method"]

        if best_val is not None:
            label = best_metric_name.replace("_", " ")
            if 0 <= best_val <= 1:
                progress("result", f"Best: {best_method} ({best_val:.1%} {label})")
            else:
                progress("result", f"Best: {best_method} ({best_val:.4g} {label})")

        # Key observations from last run
        last = runs[-1]
        if last.get("observation"):
            obs = last["observation"][:200]
            if len(last["observation"]) > 200:
                obs += "…"
            progress("phase", f"Latest: {obs}")

        # Next step from last run
        if last.get("next_step"):
            ns = last["next_step"][:150]
            if len(last["next_step"]) > 150:
                ns += "…"
            progress("phase", f"Next: {ns}")

        progress("phase", "")
    except Exception as exc:
        logger.warning("Run summary generation failed: %s", exc)
