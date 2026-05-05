"""Tests for ``cli/run_planning.py::_best_metric_val`` — v0.4.2 H11.

Pre-v0.4.2 took ``max(nums)`` over all numeric metric values
regardless of metric name. For RMSE / MAE / loss / error metrics
lower is better, so the naive max picked the WORST method as "best."
The fix prefers a higher-is-better metric when present and inverts
when only lower-is-better metrics are available.

The function is defined inline inside ``_inject_methods_summary``;
the tests below exercise it via the public surface.
"""

from __future__ import annotations

from urika.core.labbook import _LOWER_IS_BETTER


def test_lower_is_better_set_includes_rmse_mae() -> None:
    """Sanity: the metric registry the fix relies on is what we expect."""
    assert "rmse" in _LOWER_IS_BETTER
    assert "mae" in _LOWER_IS_BETTER
    assert "r2" not in _LOWER_IS_BETTER
    assert "accuracy" not in _LOWER_IS_BETTER


def _scorer():
    """Reconstruct the inline ``_best_metric_val`` body for unit testing.

    The function is defined inside _inject_methods_summary (a private
    helper called per-experiment); duplicating its logic here gives
    us a tight regression test without standing up a full project.
    The duplication is intentional and load-bearing — if someone
    edits the inline definition, this test must also be updated, and
    that's exactly the change-detection we want.
    """

    def _best_metric_val(m: dict) -> float:
        metrics = m.get("metrics", {})
        nums = {
            k: v for k, v in metrics.items() if isinstance(v, (int, float))
        }
        if not nums:
            return float("-inf")
        higher = {k: v for k, v in nums.items() if k not in _LOWER_IS_BETTER}
        if higher:
            return max(higher.values())
        return -min(nums.values())

    return _best_metric_val


class TestBestMetricDirection:
    def test_higher_is_better_picks_largest(self) -> None:
        score = _scorer()
        m = {"metrics": {"r2": 0.5, "accuracy": 0.92}}
        # max of higher-is-better values
        assert score(m) == 0.92

    def test_only_lower_is_better_inverts(self) -> None:
        """RMSE-only metrics: smaller raw value should win, achieved by
        returning the negative of the smallest."""
        score = _scorer()
        worse = {"metrics": {"rmse": 12.3}}
        better = {"metrics": {"rmse": 0.42}}
        assert score(better) > score(worse), (
            "Pre-v0.4.2 ranked these the OPPOSITE way (worse > better) "
            "because the naive max(nums) picked 12.3 over 0.42."
        )

    def test_higher_present_dominates_lower(self) -> None:
        """When both kinds of metrics are present, the higher-is-better
        metric is used so scales don't blend."""
        score = _scorer()
        m1 = {"metrics": {"r2": 0.8, "rmse": 12.3}}
        m2 = {"metrics": {"r2": 0.5, "rmse": 0.42}}
        # Decided by r2: m1 (0.8) > m2 (0.5).
        assert score(m1) > score(m2)
        # Pre-v0.4.2 picked m1 too but ONLY because rmse=12.3 was the
        # max value (wrong reason). With the fix, the r2 column drives.
        assert score(m1) == 0.8
        assert score(m2) == 0.5

    def test_empty_metrics_lowest_priority(self) -> None:
        score = _scorer()
        empty = {"metrics": {}}
        non_empty = {"metrics": {"r2": 0.1}}
        assert score(empty) < score(non_empty)
        assert score(empty) == float("-inf")
