"""Tests for success criteria validation."""

from __future__ import annotations

from urika.evaluation.criteria import validate_criteria


class TestValidateCriteria:
    """Tests for validate_criteria."""

    def test_all_pass(self) -> None:
        """Metrics that meet all criteria pass."""
        metrics = {"r2": 0.95, "rmse": 0.5}
        criteria = {"r2": {"min": 0.9}, "rmse": {"max": 1.0}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []

    def test_min_failure(self) -> None:
        """Metric below min threshold fails."""
        metrics = {"r2": 0.7}
        criteria = {"r2": {"min": 0.9}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 1
        assert "r2" in failures[0]
        assert "0.7" in failures[0]
        assert "0.9" in failures[0]
        assert "min" in failures[0]

    def test_max_failure(self) -> None:
        """Metric above max threshold fails."""
        metrics = {"rmse": 2.5}
        criteria = {"rmse": {"max": 1.0}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 1
        assert "rmse" in failures[0]
        assert "2.5" in failures[0]
        assert "1.0" in failures[0]
        assert "max" in failures[0]

    def test_multiple_failures(self) -> None:
        """Both min and max failures are reported."""
        metrics = {"r2": 0.5, "rmse": 3.0}
        criteria = {"r2": {"min": 0.9}, "rmse": {"max": 1.0}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 2

    def test_missing_metric_skipped(self) -> None:
        """Metric in criteria but absent from run is skipped."""
        metrics = {"r2": 0.95}
        criteria = {"r2": {"min": 0.9}, "rmse": {"max": 1.0}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []

    def test_metadata_entries_skipped(self) -> None:
        """Criteria entries without min/max are skipped."""
        metrics = {"r2": 0.5}
        criteria = {"notes": {"type": "metadata"}, "r2": {"min": 0.4}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []

    def test_empty_criteria(self) -> None:
        """Empty criteria dict means everything passes."""
        metrics = {"r2": 0.5}
        passed, failures = validate_criteria(metrics, {})
        assert passed is True
        assert failures == []

    def test_empty_metrics(self) -> None:
        """Empty metrics dict — all criteria skipped, passes."""
        criteria = {"r2": {"min": 0.9}}
        passed, failures = validate_criteria({}, criteria)
        assert passed is True
        assert failures == []

    def test_both_min_and_max(self) -> None:
        """Range criteria (both min and max) passes when value is in range."""
        metrics = {"r2": 0.95}
        criteria = {"r2": {"min": 0.9, "max": 1.0}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []

    def test_both_min_and_max_fail_min(self) -> None:
        """Range criteria fails when value is below min."""
        metrics = {"r2": 0.8}
        criteria = {"r2": {"min": 0.9, "max": 1.0}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 1
        assert "min" in failures[0]

    def test_exact_threshold_passes(self) -> None:
        """Value exactly equal to min threshold passes (not strict)."""
        metrics = {"r2": 0.9}
        criteria = {"r2": {"min": 0.9}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []
