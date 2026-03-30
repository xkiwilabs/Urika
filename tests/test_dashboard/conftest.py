"""Dashboard test fixtures."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def dashboard_project(tmp_path):
    """Create a minimal project structure for dashboard tests."""
    # urika.toml
    toml_content = '[project]\nname = "test-project"\nquestion = "Test question"\nmode = "exploratory"\n'
    (tmp_path / "urika.toml").write_text(toml_content)

    # experiments
    exp_dir = tmp_path / "experiments" / "exp-001-baseline"
    (exp_dir / "labbook").mkdir(parents=True)
    (exp_dir / "artifacts").mkdir(parents=True)
    (exp_dir / "presentation").mkdir(parents=True)
    (exp_dir / "labbook" / "notes.md").write_text("# Notes\n\nSome notes here.\n")
    (exp_dir / "labbook" / "summary.md").write_text("# Summary\n\nBaseline results.\n")
    (exp_dir / "artifacts" / "results.png").write_bytes(b"fake-png")
    (exp_dir / "experiment.json").write_text('{"name": "baseline"}')
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "runs": [{"method": "linear", "metrics": {"r2": 0.73}}],
                "status": "completed",
            }
        )
    )

    # projectbook
    pb = tmp_path / "projectbook"
    pb.mkdir()
    (pb / "key-findings.md").write_text("# Key Findings\n\nBest r2: 0.73\n")
    (pb / "results-summary.md").write_text(
        "# Results\n\n| Method | R2 |\n|---|---|\n| linear | 0.73 |\n"
    )

    # methods.json
    (tmp_path / "methods.json").write_text(
        json.dumps(
            {
                "methods": [
                    {
                        "name": "linear_regression",
                        "status": "tested",
                        "metrics": {"r2": 0.73},
                        "experiment_id": "exp-001-baseline",
                    }
                ]
            }
        )
    )

    # criteria.json
    (tmp_path / "criteria.json").write_text(
        json.dumps(
            {
                "versions": [
                    {"version": 1, "criteria": {"threshold": {"r2": {"min": 0.7}}}}
                ]
            }
        )
    )

    # data dir
    (tmp_path / "data").mkdir()

    return tmp_path
