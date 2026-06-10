"""Tests for the per-project metrics glossary (``core/metrics_glossary.py``).

``write_metrics_glossary`` renders ``projectbook/METRICS.md`` from the
metric names observed in progress.json runs across all experiments:
static plain-language definitions for known metrics (the module-level
``METRIC_GLOSSARY``), direction via ``evaluation.ranking``, observed
range + best run via ``select_best_run``, CI when the best run carries
one, and an observed-range-only section for project-specific metrics.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.core.metrics_glossary import (
    METRIC_GLOSSARY,
    write_metrics_glossary,
)


def _write_progress(proj: Path, exp_id: str, runs: list[dict]) -> None:
    exp = proj / "experiments" / exp_id
    exp.mkdir(parents=True, exist_ok=True)
    (exp / "progress.json").write_text(
        json.dumps({"runs": runs, "status": "completed"}), encoding="utf-8"
    )


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "projectbook").mkdir()
    _write_progress(
        proj,
        "exp-001",
        [
            {
                "run_id": "run-001",
                "method": "linear_regression",
                "params": {},
                "metrics": {"r2": 0.41, "rmse": 0.21, "custom_score": 3.2},
            },
            {
                "run_id": "run-002",
                "method": "ridge",
                "params": {},
                "metrics": {"r2": 0.55, "rmse": 0.15, "custom_score": 1.8},
                "metrics_with_uncertainty": {
                    "r2": {
                        "value": 0.55,
                        "ci_lower": 0.47,
                        "ci_upper": 0.62,
                        "confidence": 0.95,
                    }
                },
            },
        ],
    )
    return proj


def _section(body: str, metric: str) -> str:
    """The text of one ``## <metric>`` section."""
    for chunk in body.split("\n## "):
        if chunk.startswith(metric):
            return chunk
    raise AssertionError(f"no section for {metric!r} in:\n{body}")


class TestWriteMetricsGlossary:
    def test_writes_metrics_md(self, project_dir: Path) -> None:
        path = write_metrics_glossary(project_dir)
        assert path == project_dir / "projectbook" / "METRICS.md"
        assert path.exists()

    def test_known_metric_gets_definition_and_direction(
        self, project_dir: Path
    ) -> None:
        body = write_metrics_glossary(project_dir).read_text(encoding="utf-8")
        r2 = _section(body, "r2")
        assert "variance" in r2  # plain-language definition
        assert "Higher is better" in r2
        rmse = _section(body, "rmse")
        assert "Lower is better" in rmse

    def test_observed_range_and_best_value(self, project_dir: Path) -> None:
        body = write_metrics_glossary(project_dir).read_text(encoding="utf-8")
        r2 = _section(body, "r2")
        assert "0.41" in r2 and "0.55" in r2  # observed range
        assert "run-002" in r2  # best-run provenance
        assert "exp-001" in r2
        rmse = _section(body, "rmse")
        # rmse is lower-is-better: best is 0.15 from run-002
        assert "0.15" in rmse and "run-002" in rmse

    def test_ci_rendered_when_best_run_carries_one(self, project_dir: Path) -> None:
        body = write_metrics_glossary(project_dir).read_text(encoding="utf-8")
        assert "[95% CI 0.47–0.62]" in _section(body, "r2")

    def test_unknown_metric_gets_observed_range_only(self, project_dir: Path) -> None:
        body = write_metrics_glossary(project_dir).read_text(encoding="utf-8")
        custom = _section(body, "custom_score")
        assert "Project-specific metric" in custom
        assert "1.8" in custom and "3.2" in custom  # observed range
        # No invented direction or best-value claim for unknown metrics.
        assert "better" not in custom
        assert "Best:" not in custom

    def test_suffix_variant_maps_to_base_definition(self, tmp_path: Path) -> None:
        proj = tmp_path / "suffix"
        proj.mkdir()
        _write_progress(
            proj,
            "exp-001",
            [
                {
                    "run_id": "run-001",
                    "method": "m",
                    "params": {},
                    "metrics": {"val_rmse": 0.3},
                }
            ],
        )
        body = write_metrics_glossary(proj).read_text(encoding="utf-8")
        section = _section(body, "val_rmse")
        assert "Lower is better" in section
        assert "error" in section.lower()  # rmse definition applies

    def test_cohens_d_direction_is_signed_magnitude(self, tmp_path: Path) -> None:
        """Signed-magnitude metrics (Cohen's d) must not claim "Higher
        is better" — the sign encodes direction, not quality."""
        proj = tmp_path / "signed"
        proj.mkdir()
        _write_progress(
            proj,
            "exp-001",
            [
                {
                    "run_id": "run-001",
                    "method": "paired_t_test",
                    "params": {},
                    "metrics": {"cohens_d": 0.5},
                }
            ],
        )
        body = write_metrics_glossary(proj).read_text(encoding="utf-8")
        section = _section(body, "cohens_d")
        assert (
            "**Direction.** Magnitude matters; the sign indicates "
            "direction of the effect." in section
        )
        assert "Higher is better" not in section
        assert "Lower is better" not in section

    def test_no_runs_returns_none(self, tmp_path: Path) -> None:
        proj = tmp_path / "empty"
        proj.mkdir()
        assert write_metrics_glossary(proj) is None
        assert not (proj / "projectbook" / "METRICS.md").exists()

    def test_runs_without_metrics_return_none(self, tmp_path: Path) -> None:
        proj = tmp_path / "nometrics"
        proj.mkdir()
        _write_progress(
            proj,
            "exp-001",
            [{"run_id": "run-001", "method": "m", "params": {}, "metrics": {}}],
        )
        assert write_metrics_glossary(proj) is None

    def test_rewrites_are_versioned(self, project_dir: Path) -> None:
        write_metrics_glossary(project_dir)
        write_metrics_glossary(project_dir)
        versions = list((project_dir / "projectbook").glob("METRICS-*.md"))
        assert versions, "second write must preserve the first as a dated version"

    def test_non_numeric_values_do_not_crash(self, tmp_path: Path) -> None:
        proj = tmp_path / "weird"
        proj.mkdir()
        _write_progress(
            proj,
            "exp-001",
            [
                {
                    "run_id": "run-001",
                    "method": "m",
                    "params": {},
                    "metrics": {"verdict": "good", "flag": True, "r2": 0.5},
                }
            ],
        )
        body = write_metrics_glossary(proj).read_text(encoding="utf-8")
        assert "## r2" in body
        # Non-numeric metrics still get a section, without a fabricated range.
        assert "## verdict" in body

    def test_metrics_across_experiments_are_pooled(self, project_dir: Path) -> None:
        _write_progress(
            project_dir,
            "exp-002",
            [
                {
                    "run_id": "run-001",
                    "method": "gbm",
                    "params": {},
                    "metrics": {"r2": 0.71},
                }
            ],
        )
        body = write_metrics_glossary(project_dir).read_text(encoding="utf-8")
        r2 = _section(body, "r2")
        assert "0.71" in r2 and "exp-002" in r2  # cross-experiment best


class TestMetricGlossarySeed:
    def test_seed_entries_present(self) -> None:
        expected = {
            "r2",
            "rmse",
            "mse",
            "mae",
            "accuracy",
            "precision",
            "recall",
            "f1",
            "auc",
            "p_value",
            "cohens_d",
            "log_loss",
            "silhouette",
            "aic",
            "bic",
        }
        assert expected <= set(METRIC_GLOSSARY)

    def test_entries_carry_definition_range_and_how_to_read(self) -> None:
        for name, entry in METRIC_GLOSSARY.items():
            assert entry.get("definition"), f"{name} missing definition"
            assert entry.get("range"), f"{name} missing range"
            assert entry.get("how_to_read"), f"{name} missing how_to_read"
