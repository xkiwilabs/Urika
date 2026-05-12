"""Output parsing for agent text responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from urika.core.models import RunRecord

logger = logging.getLogger(__name__)


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """Find all ```json fenced blocks in text, parse them, skip malformed.

    Pre-v0.4.2 the regex required a literal ``\\n`` between the
    language tag and the body, so single-line code blocks like
    `` ```json {"foo": 1} ``` `` (which some Claude responses
    actually emit) were silently dropped. The relaxed pattern
    accepts the language tag followed by any whitespace, including
    none.
    """
    pattern = re.compile(r"```(?:json|JSON)\s*(.*?)```", re.DOTALL)
    results: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            # Pre-v0.4 this silently `continue`d. A malformed
            # evaluator/advisor JSON block is the single most common
            # reason ``criteria_met`` is silently missed and the loop
            # runs to max_turns wondering why criteria never matched —
            # or the advisor's only suggestion is dropped and the
            # meta-loop bails with "no further experiments to suggest".
            # v0.4.4: promoted debug -> warning so it lands in run.log /
            # the dashboard SSE feed / the e2e smoke logs by default.
            preview = raw[:120].replace("\n", "\\n")
            logger.warning(
                "Skipping malformed JSON block in agent output: %s: %s; raw[:120]=%r",
                type(exc).__name__,
                exc,
                preview,
            )
            continue
        if isinstance(parsed, dict):
            results.append(parsed)
    return results


def parse_run_records(text: str) -> list[RunRecord]:
    """Extract RunRecords from JSON blocks that have run_id, method, and metrics.

    Pre-v0.4.2 the only check was membership-of-key; an agent that
    emitted ``"metrics": "great"`` (string instead of dict) created
    a RunRecord with a non-dict ``metrics`` field that crashed
    downstream consumers (``metrics.values()`` / ``metrics.items()``).
    Now we type-check ``metrics`` and ``params`` and skip the record
    with a debug log if either is wrong.
    """
    blocks = _extract_json_blocks(text)
    records: list[RunRecord] = []
    for block in blocks:
        if not all(k in block for k in ("run_id", "method", "metrics")):
            continue
        metrics = block["metrics"]
        if not isinstance(metrics, dict):
            logger.warning(
                "Skipping run record with non-dict metrics (%s): run_id=%r",
                type(metrics).__name__,
                block.get("run_id"),
            )
            continue
        params = block.get("params", {})
        if not isinstance(params, dict):
            logger.warning(
                "Skipping run record with non-dict params (%s): run_id=%r",
                type(params).__name__,
                block.get("run_id"),
            )
            continue
        records.append(
            RunRecord(
                run_id=block["run_id"],
                method=block["method"],
                params=params,
                metrics=metrics,
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
