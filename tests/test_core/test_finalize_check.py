"""Tests for the deterministic post-finalize integrity validator.

``validate_finalize_artifacts`` is a best-effort, WARN-only pass run
after the finalize sequence has written findings.json, the standalone
method scripts, reproduce.sh, and model cards. It returns a list of
human-readable warning strings (empty == clean) and NEVER raises — a
corrupt/missing findings.json yields a single graceful warning, not an
exception. These tests pin every check and the graceful-degradation
behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

from urika.core.finalize_check import validate_finalize_artifacts


def _make_project(
    tmp_path: Path,
    *,
    findings: dict | str | None,
    scripts: dict[str, str] | None = None,
    progress: dict[str, dict] | None = None,
    figures: list[str] | None = None,
    reproduce_sh: str | None = None,
    reproduce_bat: str | None = None,
) -> Path:
    """Build a synthetic finalized project directory.

    - *findings*: a dict (written as findings.json), a raw string
      (written verbatim — for the corrupt case), or None (no file).
    - *scripts*: {relpath: body} written under project_dir.
    - *progress*: {experiment_id: progress.json dict}.
    - *figures*: relative figure paths to create as real files.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "projectbook").mkdir()

    if findings is not None:
        fp = proj / "projectbook" / "findings.json"
        if isinstance(findings, str):
            fp.write_text(findings, encoding="utf-8")
        else:
            fp.write_text(json.dumps(findings), encoding="utf-8")

    for rel, body in (scripts or {}).items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    for exp_id, data in (progress or {}).items():
        exp = proj / "experiments" / exp_id
        exp.mkdir(parents=True, exist_ok=True)
        (exp / "progress.json").write_text(json.dumps(data), encoding="utf-8")

    for fig in figures or []:
        p = proj / fig
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n")

    if reproduce_sh is not None:
        (proj / "reproduce.sh").write_text(reproduce_sh, encoding="utf-8")
    if reproduce_bat is not None:
        (proj / "reproduce.bat").write_text(reproduce_bat, encoding="utf-8")

    return proj


def _clean_findings() -> dict:
    return {
        "final_methods": [
            {
                "name": "ridge",
                "script": "methods/final_ridge.py",
                "run_id": "run-001",
                "experiment_id": "exp-001",
            }
        ],
        "selected_figures": ["projectbook/figures/result.png"],
    }


def _clean_progress() -> dict[str, dict]:
    return {
        "exp-001": {
            "experiment_id": "exp-001",
            "runs": [{"run_id": "run-001", "method": "ridge", "metrics": {"r2": 0.4}}],
        }
    }


def test_clean_project_returns_no_warnings(tmp_path: Path):
    proj = _make_project(
        tmp_path,
        findings=_clean_findings(),
        scripts={"methods/final_ridge.py": "print('x')\n"},
        progress=_clean_progress(),
        figures=["projectbook/figures/result.png"],
        reproduce_sh=(
            "#!/usr/bin/env bash\npip install -r requirements.txt\n"
            "python methods/final_ridge.py --data data/x.csv\n"
        ),
    )
    assert validate_finalize_artifacts(proj) == []


def test_missing_script_warns(tmp_path: Path):
    proj = _make_project(
        tmp_path,
        findings=_clean_findings(),
        # no script written
        progress=_clean_progress(),
        figures=["projectbook/figures/result.png"],
    )
    warnings = validate_finalize_artifacts(proj)
    assert any("ridge" in w and "methods/final_ridge.py" in w for w in warnings), (
        warnings
    )


def test_cross_experiment_run_id_warns_naming_both(tmp_path: Path):
    findings = _clean_findings()
    findings["final_methods"][0]["experiment_id"] = "exp-002"
    proj = _make_project(
        tmp_path,
        findings=findings,
        scripts={"methods/final_ridge.py": "print('x')\n"},
        progress={
            "exp-001": {
                "runs": [{"run_id": "run-001", "method": "ridge", "metrics": {}}]
            },
            "exp-002": {"runs": []},
        },
        figures=["projectbook/figures/result.png"],
    )
    warnings = validate_finalize_artifacts(proj)
    assert any(
        "run-001" in w and "exp-002" in w and "exp-001" in w for w in warnings
    ), warnings


def test_run_id_nowhere_warns(tmp_path: Path):
    findings = _clean_findings()
    findings["final_methods"][0]["run_id"] = "run-999"
    proj = _make_project(
        tmp_path,
        findings=findings,
        scripts={"methods/final_ridge.py": "print('x')\n"},
        progress=_clean_progress(),
        figures=["projectbook/figures/result.png"],
    )
    warnings = validate_finalize_artifacts(proj)
    assert any(
        "run-999" in w and "not found in any experiment" in w for w in warnings
    ), warnings


def test_missing_selected_figure_warns(tmp_path: Path):
    proj = _make_project(
        tmp_path,
        findings=_clean_findings(),
        scripts={"methods/final_ridge.py": "print('x')\n"},
        progress=_clean_progress(),
        # no figure created
    )
    warnings = validate_finalize_artifacts(proj)
    assert any("figure" in w and "result.png" in w for w in warnings), warnings


def test_reproduce_sh_missing_script_warns(tmp_path: Path):
    proj = _make_project(
        tmp_path,
        findings=_clean_findings(),
        scripts={"methods/final_ridge.py": "print('x')\n"},
        progress=_clean_progress(),
        figures=["projectbook/figures/result.png"],
        reproduce_sh=(
            "#!/usr/bin/env bash\npython methods/does_not_exist.py --data data/x.csv\n"
        ),
    )
    warnings = validate_finalize_artifacts(proj)
    assert any("reproduce.sh" in w and "does_not_exist.py" in w for w in warnings), (
        warnings
    )


def test_corrupt_findings_returns_single_graceful_warning(tmp_path: Path):
    proj = _make_project(tmp_path, findings="{ this is not valid json ")
    warnings = validate_finalize_artifacts(proj)
    assert len(warnings) == 1
    assert "findings.json" in warnings[0].lower()


def test_missing_findings_returns_single_graceful_warning(tmp_path: Path):
    proj = _make_project(tmp_path, findings=None)
    warnings = validate_finalize_artifacts(proj)
    assert len(warnings) == 1
    assert "findings.json" in warnings[0].lower()


def test_figure_resolved_by_basename_search(tmp_path: Path):
    """A bare basename in selected_figures resolves via the project-wide
    figure search (experiments/*/artifacts + projectbook/figures)."""
    findings = _clean_findings()
    findings["selected_figures"] = ["result.png"]
    proj = _make_project(
        tmp_path,
        findings=findings,
        scripts={"methods/final_ridge.py": "print('x')\n"},
        progress=_clean_progress(),
    )
    # place the figure under an experiment artifacts dir
    art = proj / "experiments" / "exp-001" / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "result.png").write_bytes(b"\x89PNG\r\n")
    assert validate_finalize_artifacts(proj) == []


def test_traversal_path_in_findings_does_not_escape(tmp_path: Path):
    """A ``../`` script path in a bad findings entry must be treated as
    not-found, never resolved outside the project sandbox."""
    findings = _clean_findings()
    findings["final_methods"][0]["script"] = "../../../etc/passwd"
    proj = _make_project(
        tmp_path,
        findings=findings,
        progress=_clean_progress(),
        figures=["projectbook/figures/result.png"],
    )
    warnings = validate_finalize_artifacts(proj)
    assert any("script not found" in w for w in warnings), warnings
