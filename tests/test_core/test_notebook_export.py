"""Tests for the reproduce-notebook generator (``core/notebook_export.py``).

``urika finalize`` writes ``projectbook/reproduce.ipynb`` by pure code
(no agent) from findings.json + the standalone method scripts the
finalizer already wrote. Core contracts pinned here:

- structure: title md cell (question + answer), setup code cell
  (commented ``%pip install -r requirements.txt`` + sys.path note),
  one md cell + one code cell per final method (the code cell is an
  argv-neutralizing ``sys.argv`` preamble followed by the LITERAL
  script file contents), closing md cell pointing at METRICS.md and
  the model cards;
- a missing script file degrades to an md note WITHOUT a code cell —
  the generator never invents code;
- the notebook passes ``nbformat.validate`` before it is written and
  carries a python3 kernelspec;
- missing/malformed/empty findings.json → ``None`` (plus a log
  warning), nothing written;
- rewrites are versioned (``write_versioned`` — .ipynb is JSON text).

The end-to-end execution check lives in the gated test at the bottom
(nbclient is installed in the dev env; skipped cleanly elsewhere).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import nbformat
import pytest

from urika.core.notebook_export import write_reproduce_notebook

# Mirrors real finalizer output: an argparse CLI script whose --data
# flag has a working default relative to the project root. Inside a
# Jupyter kernel argparse would otherwise parse ipykernel's own argv
# (-f <connection file> ...) and die with SystemExit: 2 — the embedded
# cell's sys.argv preamble is what makes this runnable.
_SCRIPT = '''\
"""Synthetic stand-in for a finalizer standalone method script."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/xy.csv")
    args = parser.parse_args()
    with open(args.data, encoding="utf-8") as fh:
        print("r2 =", fh.read().strip())


if __name__ == "__main__":
    main()
'''

_FINDINGS = {
    "question": "Does X predict Y?",
    "answer": "Yes — X predicts Y with R²=0.41 in a ridge model.",
    "final_methods": [
        {
            "name": "ridge",
            "script": "methods/final_ridge.py",
            "run_id": "run-001",
            "experiment_id": "exp-001-baseline",
            "key_metrics": {"r2": 0.41},
            "summary": "Ridge regression predicts Y from X with R²=0.41.",
        }
    ],
}

_RUN = {
    "run_id": "run-001",
    "method": "ridge",
    "metrics": {"r2": 0.41},
    "metrics_with_uncertainty": {
        "r2": {
            "value": 0.41,
            "ci_lower": 0.33,
            "ci_upper": 0.49,
            "confidence": 0.95,
        }
    },
}


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "proj"\nquestion = "Does X predict Y?"\n'
        'mode = "exploratory"\ndescription = ""\n',
        encoding="utf-8",
    )
    exp = proj / "experiments" / "exp-001-baseline"
    exp.mkdir(parents=True)
    (exp / "progress.json").write_text(
        json.dumps({"runs": [_RUN], "status": "completed"}), encoding="utf-8"
    )
    (proj / "projectbook").mkdir()
    (proj / "projectbook" / "findings.json").write_text(
        json.dumps(_FINDINGS), encoding="utf-8"
    )
    (proj / "methods").mkdir()
    (proj / "methods" / "final_ridge.py").write_text(_SCRIPT, encoding="utf-8")
    (proj / "data").mkdir()
    (proj / "data" / "xy.csv").write_text("0.41\n", encoding="utf-8")
    return proj


def _read(path: Path) -> nbformat.NotebookNode:
    return nbformat.read(path, as_version=4)


class TestWriteReproduceNotebook:
    def test_writes_to_projectbook(self, project_dir: Path) -> None:
        path = write_reproduce_notebook(project_dir)
        assert path == project_dir / "projectbook" / "reproduce.ipynb"
        assert path.exists()

    def test_notebook_is_valid(self, project_dir: Path) -> None:
        path = write_reproduce_notebook(project_dir)
        nbformat.validate(_read(path))  # raises on invalid

    def test_kernelspec_is_python3(self, project_dir: Path) -> None:
        nb = _read(write_reproduce_notebook(project_dir))
        assert nb.metadata["kernelspec"]["name"] == "python3"

    def test_title_cell_has_question_and_answer(self, project_dir: Path) -> None:
        nb = _read(write_reproduce_notebook(project_dir))
        title = nb.cells[0]
        assert title.cell_type == "markdown"
        assert "Does X predict Y?" in title.source
        assert "R²=0.41 in a ridge model" in title.source

    def test_setup_cell_has_commented_pip_install(self, project_dir: Path) -> None:
        nb = _read(write_reproduce_notebook(project_dir))
        setup = nb.cells[1]
        assert setup.cell_type == "code"
        assert "# %pip install -r requirements.txt" in setup.source, (
            "the pip install must be present but commented out"
        )
        assert "sys.path" in setup.source

    def test_method_markdown_cell_has_name_metrics_ci_summary(
        self, project_dir: Path
    ) -> None:
        nb = _read(write_reproduce_notebook(project_dir))
        md_cells = [c.source for c in nb.cells if c.cell_type == "markdown"]
        method_md = next(s for s in md_cells if s.startswith("## ridge"))
        assert "r2=0.41" in method_md
        assert "[95% CI 0.33–0.49]" in method_md, (
            "key metrics must quote the CI from the matched run record"
        )
        assert "Ridge regression predicts Y from X" in method_md

    def test_method_code_cell_ends_with_literal_script(self, project_dir: Path) -> None:
        nb = _read(write_reproduce_notebook(project_dir))
        code_sources = [c.source for c in nb.cells if c.cell_type == "code"]
        assert any(s.strip().endswith(_SCRIPT.strip()) for s in code_sources), (
            "the method code cell must carry the script file contents verbatim "
            "(below the argv preamble)"
        )

    def test_method_code_cell_starts_with_argv_preamble(
        self, project_dir: Path
    ) -> None:
        """The embedded cell must neutralize Jupyter's own argv before
        the script body runs — real finalizer scripts are argparse CLIs
        and would otherwise exit with SystemExit: 2 inside ipykernel."""
        nb = _read(write_reproduce_notebook(project_dir))
        cell = next(
            c.source
            for c in nb.cells
            if c.cell_type == "code" and _SCRIPT.strip() in c.source
        )
        preamble, _, _ = cell.partition(_SCRIPT.strip())
        assert "import sys" in preamble
        assert 'sys.argv = ["final_ridge.py"]' in preamble, (
            "sys.argv must be reset to just the script's own filename"
        )

    def test_missing_script_noted_without_code_cell(self, project_dir: Path) -> None:
        (project_dir / "methods" / "final_ridge.py").unlink()
        nb = _read(write_reproduce_notebook(project_dir))
        nbformat.validate(nb)
        md_cells = [c.source for c in nb.cells if c.cell_type == "markdown"]
        assert any(
            "methods/final_ridge.py" in s and "not found" in s for s in md_cells
        ), "a missing script must be noted in markdown"
        code_sources = [c.source for c in nb.cells if c.cell_type == "code"]
        assert all("final_ridge" not in s for s in code_sources), (
            "no code cell may be fabricated for a missing script"
        )

    def test_closing_cell_points_at_metrics_and_model_cards(
        self, project_dir: Path
    ) -> None:
        nb = _read(write_reproduce_notebook(project_dir))
        closing = nb.cells[-1]
        assert closing.cell_type == "markdown"
        assert "METRICS.md" in closing.source
        assert "model card" in closing.source.lower()

    def test_missing_findings_returns_none(self, tmp_path: Path) -> None:
        proj = tmp_path / "bare"
        proj.mkdir()
        assert write_reproduce_notebook(proj) is None
        assert not (proj / "projectbook" / "reproduce.ipynb").exists()

    def test_empty_final_methods_returns_none(self, project_dir: Path) -> None:
        (project_dir / "projectbook" / "findings.json").write_text(
            json.dumps({"question": "Q?", "final_methods": []}), encoding="utf-8"
        )
        assert write_reproduce_notebook(project_dir) is None

    def test_malformed_findings_returns_none(self, project_dir: Path) -> None:
        (project_dir / "projectbook" / "findings.json").write_text(
            "{not json", encoding="utf-8"
        )
        assert write_reproduce_notebook(project_dir) is None

    def test_rewrites_are_versioned(self, project_dir: Path) -> None:
        write_reproduce_notebook(project_dir)
        write_reproduce_notebook(project_dir)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sibling = project_dir / "projectbook" / f"reproduce-{stamp}.ipynb"
        assert sibling.exists(), "rewrites must preserve the previous notebook"


@pytest.mark.integration
def test_notebook_executes_end_to_end(project_dir: Path) -> None:
    """Execution check on a fresh kernel — gated on nbclient (installed
    in the dev env per the v0.9.0 plan; skipped cleanly elsewhere).

    The embedded script is an argparse CLI with a ``__main__`` guard,
    mirroring real finalizer output. Without the cell's sys.argv
    preamble argparse would parse ipykernel's argv and raise
    SystemExit: 2, so this test fails if the preamble is dropped."""
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")

    path = write_reproduce_notebook(project_dir)
    nb = _read(path)
    client = nbclient.NotebookClient(
        nb, timeout=120, resources={"metadata": {"path": str(project_dir)}}
    )
    executed = client.execute()
    outputs = [
        out
        for cell in executed.cells
        if cell.cell_type == "code"
        for out in cell.get("outputs", [])
    ]
    assert any("r2 = 0.41" in "".join(out.get("text", "")) for out in outputs), (
        "the embedded method script must actually run and print its metric"
    )
