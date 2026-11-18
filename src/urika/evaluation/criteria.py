"""Success criteria validation."""

from __future__ import annotations

import math
from typing import Any

_HIGHER = {"higher", "higher_is_better", ">", ">=", "max", "maximize", "maximise"}
_LOWER = {"lower", "lower_is_better", "<", "<=", "min", "minimize", "minimise"}


def normalise_direction(direction: Any, metric: str = "") -> str:
    """Map the direction spellings agents use onto ``"higher"`` /
    ``"lower"``. Unknown or missing → inferred from the metric name."""
    from urika.evaluation.ranking import metric_direction

    d = str(direction or "").strip().lower()
    if d in _HIGHER:
        return "higher"
    if d in _LOWER:
        return "lower"
    return metric_direction(metric) if metric else "higher"


def _target_entries(threshold: dict[str, Any]) -> list[tuple[str, float, str]]:
    """``(metric, target, direction)`` for every target in a threshold
    layer, in either schema: ``{"primary": {metric, target, direction},
    "secondary": {...}}`` or the legacy ``{metric: {"min"|"max": x}}``."""
    out: list[tuple[str, float, str]] = []
    for key, spec in threshold.items():
        if not isinstance(spec, dict):
            continue
        if key in ("primary", "secondary") or "metric" in spec:
            metric = spec.get("metric")
            target = spec.get("target")
            if not isinstance(metric, str) or not isinstance(target, (int, float)):
                continue
            if isinstance(target, bool):
                continue
            out.append(
                (
                    metric,
                    float(target),
                    normalise_direction(spec.get("direction"), metric),
                )
            )
            continue
        if "min" in spec and isinstance(spec["min"], (int, float)):
            out.append((key, float(spec["min"]), "higher"))
        if "max" in spec and isinstance(spec["max"], (int, float)):
            out.append((key, float(spec["max"]), "lower"))
    return out


def validate_threshold(
    metrics: dict[str, Any],
    threshold: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check metrics against a criteria ``threshold`` layer.

    Unlike ``validate_criteria`` this is never vacuous: an empty layer,
    or a target whose metric the run did not report, is **not met**.
    Neither is a non-finite value (NaN compares False against any target,
    and +/-inf beats every target in one direction).
    Returns ``(met, failure_messages)``.
    """
    entries = _target_entries(threshold) if isinstance(threshold, dict) else []
    if not entries:
        return False, ["threshold layer defines no checkable target"]
    failures: list[str] = []
    for metric, target, direction in entries:
        value = metrics.get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            failures.append(f"{metric}: missing from run metrics (target {target})")
            continue
        if not math.isfinite(value):
            failures.append(
                f"{metric}: {value} is not a finite number (target {target})"
            )
            continue
        if direction == "higher" and value < target:
            failures.append(f"{metric}: {value} < {target} (higher is better)")
        elif direction == "lower" and value > target:
            failures.append(f"{metric}: {value} > {target} (lower is better)")
    return (len(failures) == 0, failures)


def validate_criteria(
    metrics: dict[str, float],
    criteria: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check metrics against success criteria.

    Entries with "min" or "max" keys are validated. All other entries skipped.
    Metrics not present are skipped. A non-finite value (NaN, +/-inf) fails.
    Returns (all_passed, failure_messages).
    """
    failures: list[str] = []
    for key, spec in criteria.items():
        if not isinstance(spec, dict):
            continue
        if "min" not in spec and "max" not in spec:
            continue
        if key not in metrics:
            continue
        value = metrics[key]
        if isinstance(value, (int, float)) and not math.isfinite(value):
            bounds = ", ".join(f"{b} {spec[b]}" for b in ("min", "max") if b in spec)
            failures.append(f"{key}: {value} is not a finite number ({bounds})")
            continue
        if "min" in spec and value < spec["min"]:
            failures.append(f"{key}: {value} < {spec['min']} (min)")
        if "max" in spec and value > spec["max"]:
            failures.append(f"{key}: {value} > {spec['max']} (max)")
    return (len(failures) == 0, failures)
