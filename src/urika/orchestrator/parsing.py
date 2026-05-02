"""Output parsing for agent text responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from urika.core.models import RunRecord

logger = logging.getLogger(__name__)


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """Find all ```json fenced blocks in text, parse them, skip malformed."""
    pattern = re.compile(r"```(?:json|JSON)\s*\n(.*?)```", re.DOTALL)
    results: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            # Pre-v0.4 this silently `continue`d. A malformed
            # evaluator/advisor JSON block is the single most common
            # reason ``criteria_met`` is silently missed and the loop
            # runs to max_turns wondering why criteria never matched.
            # Emit at debug so verbose runs can grep for the cause
            # without spamming normal logs.
            preview = raw[:120].replace("\n", "\\n")
            logger.debug(
                "Skipping malformed JSON block: %s: %s; raw[:120]=%r",
                type(exc).__name__,
                exc,
                preview,
            )
            continue
        if isinstance(parsed, dict):
            results.append(parsed)
    return results


def parse_run_records(text: str) -> list[RunRecord]:
    """Extract RunRecords from JSON blocks that have run_id, method, and metrics."""
    blocks = _extract_json_blocks(text)
    records: list[RunRecord] = []
    for block in blocks:
        if "run_id" in block and "method" in block and "metrics" in block:
            records.append(
                RunRecord(
                    run_id=block["run_id"],
                    method=block["method"],
                    params=block.get("params", {}),
                    metrics=block["metrics"],
                    hypothesis=block.get("hypothesis", ""),
                    observation=block.get("observation", ""),
                    next_step=block.get("next_step", ""),
                    artifacts=block.get("artifacts", []),
                )
            )
    return records


def parse_evaluation(text: str) -> dict[str, Any] | None:
    """Extract the first JSON block containing a 'criteria_met' key."""
    blocks = _extract_json_blocks(text)
    for block in blocks:
        if "criteria_met" in block:
            return block
    return None


def parse_suggestions(text: str) -> dict[str, Any] | None:
    """Extract the first JSON block containing a 'suggestions' key."""
    blocks = _extract_json_blocks(text)
    for block in blocks:
        if "suggestions" in block:
            return block
    return None


def parse_method_plan(text: str) -> dict[str, Any] | None:
    """Extract the first JSON block containing 'method_name' and 'steps' keys."""
    blocks = _extract_json_blocks(text)
    for block in blocks:
        if "method_name" in block and "steps" in block:
            return block
    return None
