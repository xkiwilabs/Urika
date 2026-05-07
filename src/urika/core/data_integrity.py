"""Runtime check: detect task-agent runs that used synthetic data.

v0.4.2 mitigation for the data-fabrication bug. The task_agent prompt
now explicitly forbids data simulation, but a belt-and-braces runtime
check scans each experiment's method scripts for evidence that the
real dataset was actually used. A run whose scripts contain
synthetic-data signals **without** any real-data references is flagged
as ``suspect`` so the orchestrator + dashboard + finalizer can surface
the warning to the user.

This is detection-only — we don't refuse the run. The signal goes into
the per-turn progress event so it lands in the live log AND in
``run.log``, and the dashboard's experiment detail view picks it up.
Surfacing the suspicion is sufficient because:

- A scientifically-trained user reviewing the output catches
  "synthetic data" immediately and re-runs.
- A non-expert user sees the warning and at minimum asks why.
- Refusing the run silently would mask a deeper prompt-engineering
  problem worth knowing about.

Patterns are heuristics — false positives are possible (e.g. a method
that legitimately uses ``np.random`` for bootstrap resampling FROM
real data). The check runs the synthetic-pattern match only when
there are NO real-data references; in that case we're confident
enough to flag.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


# Patterns that indicate a script accesses the real dataset. Any match
# counts as evidence that the run is real. We keep the list
# conservative and pandas-centric — most analytical scripts end up
# with ``pd.read_csv`` or similar regardless of method.
_REAL_DATA_PATTERNS: tuple[str, ...] = (
    r"data_paths",
    r"pd\.read_csv",
    r"pd\.read_parquet",
    r"pd\.read_excel",
    r"pd\.read_json",
    r"pd\.read_hdf",
    r"pd\.read_table",
    r"pd\.read_sql",
    r"np\.load\(",
    r"np\.loadtxt",
    r"np\.genfromtxt",
    r"open\([^)]*['\"]\.?/?data/",
    r"from\s+urika\.data",
    r"from\s+urika\.tools",
)

# Patterns that indicate synthetic-data substitution. Case-insensitive.
_SYNTHETIC_PATTERNS: tuple[str, ...] = (
    r"sklearn\.datasets\.make_",
    r"\bmake_classification\b",
    r"\bmake_regression\b",
    r"\bmake_blobs\b",
    r"\bmake_moons\b",
    r"\bmake_circles\b",
    r"\bmake_friedman\d",
    r"\bmake_swiss_roll\b",
    r"\bmake_s_curve\b",
    r"def\s+(simulate_|generate_synthetic|fabricate|fake_|dummy_)",
    r"#\s*(simulating|generating synthetic|fabricating|placeholder data)",
    r"\bsynthetic\s+data\b",
    r"\bplaceholder\s+data\b",
)


def assess_run_data_source(
    experiment_dir: Path,
    project_data_paths: Iterable[str] = (),
) -> dict:
    """Scan an experiment's method scripts for real-vs-synthetic signals.

    Args:
        experiment_dir: Path of the experiment whose ``methods/*.py``
            scripts should be scanned.
        project_data_paths: Real-data file paths from
            ``urika.toml::[project].data_paths``. Their basenames are
            added to the real-data pattern set so a script referencing
            ``stroop.csv`` directly counts as real-data evidence even
            without a pandas read call.

    Returns:
        A dict::

            {
                "real_data": bool,            # at least one real-data signal
                "synthetic_only": bool,       # synthetic signals AND no real-data
                "scripts_scanned": int,
                "real_hits": list[str],       # diagnostic, capped at 5
                "synthetic_hits": list[str],  # diagnostic, capped at 5
            }

        ``synthetic_only`` is the action signal — when True the run
        looks suspect.
    """
    methods_dir = experiment_dir / "methods"
    if not methods_dir.is_dir():
        return {
            "real_data": False,
            "synthetic_only": False,
            "scripts_scanned": 0,
            "real_hits": [],
            "synthetic_hits": [],
        }

    real_path_patterns: list[str] = list(_REAL_DATA_PATTERNS)
    for raw in project_data_paths or ():
        basename = Path(str(raw)).name
        if basename:
            real_path_patterns.append(re.escape(basename))

    real_hits: list[str] = []
    synthetic_hits: list[str] = []
    scripts_scanned = 0

    for py_file in sorted(methods_dir.glob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scripts_scanned += 1

        for pat in real_path_patterns:
            if re.search(pat, text):
                real_hits.append(f"{py_file.name}::{pat}")
                break  # one signal per file is enough
        for pat in _SYNTHETIC_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                synthetic_hits.append(f"{py_file.name}::{pat}")
                break

    real_data = bool(real_hits)
    synthetic_only = bool(synthetic_hits) and not real_data
    return {
        "real_data": real_data,
        "synthetic_only": synthetic_only,
        "scripts_scanned": scripts_scanned,
        "real_hits": real_hits[:5],
        "synthetic_hits": synthetic_hits[:5],
    }


def format_suspect_warning(assessment: dict) -> str:
    """Format a one-line user-facing warning for a synthetic-only run.

    Used by the orchestrator's progress callback so the message lands
    in run.log, the dashboard's SSE log view, and the live CLI output.
    """
    if not assessment.get("synthetic_only"):
        return ""
    hits = assessment.get("synthetic_hits") or []
    sample = hits[0].split("::", 1)[-1] if hits else "unknown pattern"
    n = assessment.get("scripts_scanned", 0)
    return (
        f"⚠ SUSPECT: scanned {n} method script(s); none reference the real "
        f"dataset and at least one contains synthetic-data signals "
        f"(e.g. {sample}). The task_agent may have fabricated data instead "
        f"of using the project's data directory. Inspect the run before "
        f"trusting its metrics."
    )
