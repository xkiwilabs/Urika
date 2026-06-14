"""Deterministic post-finalize integrity validation.

``urika finalize`` produces ``projectbook/findings.json`` plus standalone
method scripts, ``reproduce.sh``/``reproduce.bat``, and model cards. A
finalizer running on a cheaper model occasionally emits findings whose
references don't match what's on disk — a ``script`` path that doesn't
exist, a ``run_id``/``experiment_id`` where the run actually lives in a
*different* experiment, a ``reproduce.sh`` invoking a script name that was
never written, or ``selected_figures`` pointing at absent files. Those
ship silently as broken reproducibility.

:func:`validate_finalize_artifacts` is a best-effort, WARN-only pass that
returns a list of human-readable warning strings (empty list == clean).
It NEVER raises: a missing/corrupt findings.json yields a single graceful
warning. The finalize hook emits each warning as a ``progress("warning",
…)`` event and writes them to ``projectbook/.finalize-warnings.txt`` — it
never blocks or fails finalize.

Path checks resolve defensively (``resolve()`` + ``is_relative_to`` the
project sandbox) so a ``../`` in a bad findings entry is treated as
not-found rather than reading outside the project.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from urika.core.progress import load_progress

logger = logging.getLogger(__name__)

# Matches ``python foo.py`` / ``python3 methods/foo.py`` invocations in a
# reproduce script — deliberately simple, not a full shell parse.
_PY_INVOKE = re.compile(r"\bpython3?\s+(\S+\.py)\b")


def validate_finalize_artifacts(project_dir: Path) -> list[str]:
    """Validate finalize-produced artifacts against on-disk reality.

    Returns a list of human-readable warning strings (empty == clean).
    Never raises — a missing/corrupt findings.json returns a single
    graceful warning.
    """
    project_dir = Path(project_dir)
    findings = _load_findings(project_dir)
    if findings is None:
        return ["findings.json missing or unreadable — skipping integrity validation"]

    warnings: list[str] = []
    warnings.extend(_check_final_methods(project_dir, findings))
    warnings.extend(_check_selected_figures(project_dir, findings))
    warnings.extend(_check_reproduce_scripts(project_dir))
    return warnings


def _load_findings(project_dir: Path) -> dict[str, Any] | None:
    """Load projectbook/findings.json defensively. ``None`` on
    missing/corrupt/non-object — mirrors model_cards._load_findings."""
    path = project_dir / "projectbook" / "findings.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Finalize check: cannot read %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _resolve_in_sandbox(project_dir: Path, rel: str) -> Path | None:
    """Resolve *rel* under *project_dir*; ``None`` if it escapes the
    sandbox (e.g. a ``../`` traversal in a bad findings entry)."""
    try:
        base = project_dir.resolve()
        candidate = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    if not candidate.is_relative_to(base):
        return None
    return candidate


def _check_final_methods(project_dir: Path, findings: dict[str, Any]) -> list[str]:
    methods = findings.get("final_methods")
    if not isinstance(methods, list):
        return []
    warnings: list[str] = []
    for entry in methods:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip() or "<unnamed>"

        script = str(entry.get("script") or "").strip()
        if script:
            resolved = _resolve_in_sandbox(project_dir, script)
            if resolved is None or not resolved.is_file():
                warnings.append(f"final method '{name}': script not found: {script}")

        run_id = str(entry.get("run_id") or "").strip()
        experiment_id = str(entry.get("experiment_id") or "").strip()
        if run_id:
            found_exp = _experiment_containing_run(project_dir, run_id)
            if found_exp is None:
                warnings.append(
                    f"final method '{name}': run_id {run_id} (experiment "
                    f"{experiment_id or '<unset>'}) not found in any experiment"
                )
            elif experiment_id and found_exp != experiment_id:
                warnings.append(
                    f"final method '{name}': run_id {run_id} not found in "
                    f"experiment {experiment_id} (found in {found_exp}) — "
                    "metrics/assumptions may be from the wrong run"
                )
    return warnings


def _experiment_containing_run(project_dir: Path, run_id: str) -> str | None:
    """The experiment_id whose progress.json / on-disk run records
    contain *run_id*, or ``None``. Mirrors model_cards._find_run_record's
    tolerance (progress.json then labbook/artifacts run-*.json)."""
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.is_dir():
        return None
    for exp_dir in sorted(experiments_dir.iterdir()):
        if not exp_dir.is_dir():
            continue
        exp_id = exp_dir.name
        for run in load_progress(project_dir, exp_id).get("runs", []):
            if isinstance(run, dict) and run.get("run_id") == run_id:
                return exp_id
        try:
            from urika.orchestrator.parsing import read_disk_run_records

            for record in read_disk_run_records(exp_dir):
                if record.run_id == run_id:
                    return exp_id
        except Exception as exc:
            logger.warning(
                "Finalize check: disk run-record scan failed for %s: %s", exp_id, exc
            )
    return None


def _check_selected_figures(project_dir: Path, findings: dict[str, Any]) -> list[str]:
    figures = findings.get("selected_figures")
    if not isinstance(figures, list):
        return []
    warnings: list[str] = []
    for item in figures:
        if isinstance(item, dict):
            path = str(item.get("path") or "").strip()
        else:
            path = str(item or "").strip()
        if not path:
            continue
        if not _figure_exists(project_dir, path):
            warnings.append(f"selected figure not found: {path}")
    return warnings


def _figure_exists(project_dir: Path, path: str) -> bool:
    """True if *path* exists relative to project_dir, or if its basename
    is found under experiments/*/artifacts or projectbook/figures."""
    resolved = _resolve_in_sandbox(project_dir, path)
    if resolved is not None and resolved.is_file():
        return True
    basename = Path(path).name
    if not basename:
        return False
    search_dirs = [project_dir / "projectbook" / "figures"]
    experiments_dir = project_dir / "experiments"
    if experiments_dir.is_dir():
        for exp_dir in experiments_dir.iterdir():
            if exp_dir.is_dir():
                search_dirs.append(exp_dir / "artifacts")
    for d in search_dirs:
        if (d / basename).is_file():
            return True
    return False


def _check_reproduce_scripts(project_dir: Path) -> list[str]:
    warnings: list[str] = []
    for fname in ("reproduce.sh", "reproduce.bat"):
        path = project_dir / fname
        if not path.exists():
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Finalize check: cannot read %s: %s", path, exc)
            continue
        for script in _PY_INVOKE.findall(body):
            resolved = _resolve_in_sandbox(project_dir, script)
            if resolved is None or not resolved.is_file():
                warnings.append(f"{fname} references missing script: {script}")
    return warnings
