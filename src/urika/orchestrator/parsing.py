"""Output parsing for agent text responses."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from urika.core.models import RunRecord

logger = logging.getLogger(__name__)


def _find_balanced_json(text: str, start: int) -> tuple[str, int] | None:
    """From ``text[start:]`` (first non-space char must be { or [),
    return (json_substring, end_index) covering the balanced object/array,
    honoring string literals and escapes. None if unbalanced."""
    i = start
    n = len(text)
    while i < n and text[i] in " \t\r\n":
        i += 1
    if i >= n or text[i] not in "{[":
        return None
    open_ch = text[i]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    j = i
    while j < n:
        c = text[j]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return text[i : j + 1], j + 1
        j += 1
    return None


def _extract_json_blocks(text: str) -> list[dict[str, Any]]:
    """Find all ```json fenced blocks in text, parse them, skip malformed.

    Pre-v0.4.2 the regex required a literal ``\\n`` between the
    language tag and the body, so single-line code blocks like
    `` ```json {"foo": 1} ``` `` (which some Claude responses
    actually emit) were silently dropped. The relaxed pattern
    accepts the language tag followed by any whitespace, including
    none.

    v0.5.0: uses brace-balanced extraction from the opening fence so a
    code fence embedded inside a JSON *string value* (e.g. a Python
    snippet in a task-agent ``observation`` field) no longer truncates
    the match at the first closing fence it sees — which previously
    dropped the whole run record and could mark an experiment
    ``failed`` with 0 runs despite real work. Falls back to the legacy
    non-greedy regex slice only if balancing fails.
    """
    results: list[dict[str, Any]] = []
    open_re = re.compile(r"```(?:json|JSON)[ \t]*\r?\n?", re.IGNORECASE)
    pos = 0
    # Manual cursor scan: on a successful balanced parse we advance ``pos``
    # past the *end* of the balanced region so a ```json opener that lives
    # inside an already-parsed JSON string value isn't re-matched (which
    # would otherwise emit a spurious "Skipping malformed JSON block"
    # warning). The unbalanced fallback advances past the opening fence only,
    # to keep the legacy behaviour and avoid an infinite loop.
    while True:
        m = open_re.search(text, pos)
        if m is None:
            break
        balanced = _find_balanced_json(text, m.end())
        if balanced is not None:
            raw = balanced[0]
            pos = balanced[1]
        else:
            tail = text[m.end() :]
            close = tail.find("```")
            raw = (tail[:close] if close != -1 else tail).strip()
            pos = m.end()
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


def _record_from_block(block: dict[str, Any]) -> RunRecord | None:
    """Validate a parsed JSON block and convert it to a RunRecord.

    Returns None (with a warning log) when the block is missing required
    fields or has the wrong type for ``metrics``/``params``. Shared
    between :func:`parse_run_records` (text channel) and
    :func:`read_labbook_run_records` (on-disk channel) so both sources
    enforce the same validation.
    """
    if not all(k in block for k in ("run_id", "method", "metrics")):
        return None
    metrics = block["metrics"]
    if not isinstance(metrics, dict):
        logger.warning(
            "Skipping run record with non-dict metrics (%s): run_id=%r",
            type(metrics).__name__,
            block.get("run_id"),
        )
        return None
    params = block.get("params", {})
    if not isinstance(params, dict):
        logger.warning(
            "Skipping run record with non-dict params (%s): run_id=%r",
            type(params).__name__,
            block.get("run_id"),
        )
        return None
    return RunRecord(
        run_id=block["run_id"],
        method=block["method"],
        params=params,
        metrics=metrics,
        hypothesis=block.get("hypothesis", ""),
        observation=block.get("observation", ""),
        next_step=block.get("next_step", ""),
        artifacts=block.get("artifacts", []),
    )


def parse_run_records(text: str) -> list[RunRecord]:
    """Extract RunRecords from ```json blocks in agent text output.

    Pre-v0.4.2 the only check was membership-of-key; an agent that
    emitted ``"metrics": "great"`` (string instead of dict) created
    a RunRecord with a non-dict ``metrics`` field that crashed
    downstream consumers (``metrics.values()`` / ``metrics.items()``).
    Validation is now shared with :func:`_record_from_block`.
    """
    records: list[RunRecord] = []
    for block in _extract_json_blocks(text):
        record = _record_from_block(block)
        if record is not None:
            records.append(record)
    return records


def read_labbook_run_records(experiment_dir: Path) -> list[RunRecord]:
    """Enumerate ``<experiment_dir>/labbook/run-*.json`` files as RunRecords.

    Modern Claude task agents frequently write run records to disk via
    Bash tool calls and emit little or no inline narration. Pre-v0.5.0.2
    the orchestrator only scanned the agent's text output for
    ```json blocks — so a tools-only agent produced no leaderboard
    update despite writing real records to disk. The loop now merges
    text-parsed records with the on-disk records this function returns
    (see :mod:`urika.orchestrator.loop` for the call site).

    Returns:
        Records sorted by filename so ``run-001-*`` lands before
        ``run-002-*``. Malformed JSON files and records missing required
        fields are skipped (same validation as :func:`parse_run_records`).
        Returns ``[]`` when ``<experiment_dir>/labbook`` doesn't exist.
    """
    labbook = experiment_dir / "labbook"
    if not labbook.is_dir():
        return []
    records: list[RunRecord] = []
    for path in sorted(labbook.glob("run-*.json")):
        try:
            block = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Skipping malformed labbook record %s: %s: %s",
                path.name,
                type(exc).__name__,
                exc,
            )
            continue
        if not isinstance(block, dict):
            logger.warning(
                "Skipping labbook record %s: top-level JSON is %s, not object",
                path.name,
                type(block).__name__,
            )
            continue
        record = _record_from_block(block)
        if record is not None:
            records.append(record)
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
