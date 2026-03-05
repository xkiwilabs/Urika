"""Success criteria validation."""

from __future__ import annotations

from typing import Any


def validate_criteria(
    metrics: dict[str, float],
    criteria: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check metrics against success criteria.

    Entries with "min" or "max" keys are validated. All other entries skipped.
    Metrics not present are skipped. Returns (all_passed, failure_messages).
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
        if "min" in spec and value < spec["min"]:
            failures.append(f"{key}: {value} < {spec['min']} (min)")
        if "max" in spec and value > spec["max"]:
            failures.append(f"{key}: {value} > {spec['max']} (max)")
    return (len(failures) == 0, failures)
