"""Tests for IMetric ABC and MetricRegistry."""

from __future__ import annotations

import numpy as np
import pytest

from urika.evaluation.metrics.base import IMetric
from urika.evaluation.metrics.registry import MetricRegistry


class DummyMetric(IMetric):
    """Concrete metric for testing."""

    def name(self) -> str:
        return "dummy"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return 0.0

    def direction(self) -> str:
        return "higher_is_better"


class AnotherMetric(IMetric):
    """A second concrete metric for testing list_all ordering."""

    def name(self) -> str:
        return "another"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return 1.0

    def direction(self) -> str:
        return "lower_is_better"


class TestIMetricInterface:
    """Test the IMetric abstract base class."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            IMetric()  # type: ignore[abstract]

    def test_concrete_implementation_works(self) -> None:
        metric = DummyMetric()
        assert metric.name() == "dummy"
        assert metric.direction() == "higher_is_better"

    def test_compute_returns_float(self) -> None:
        metric = DummyMetric()
        y_true = np.array([1.0, 2.0])
        y_pred = np.array([1.0, 2.0])
        result = metric.compute(y_true, y_pred)
        assert isinstance(result, float)


class TestMetricRegistry:
    """Test the MetricRegistry."""

    def test_register_and_get(self) -> None:
        registry = MetricRegistry()
        metric = DummyMetric()
        registry.register(metric)
        retrieved = registry.get("dummy")
        assert retrieved is metric

    def test_get_nonexistent_returns_none(self) -> None:
        registry = MetricRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all_sorted(self) -> None:
        registry = MetricRegistry()
        registry.register(DummyMetric())
        registry.register(AnotherMetric())
        names = registry.list_all()
        assert names == ["another", "dummy"]

    def test_list_all_empty(self) -> None:
        registry = MetricRegistry()
        assert registry.list_all() == []

    def test_discover_finds_metric_classes(self) -> None:
        """discover() should find all IMetric subclasses in metrics submodules."""
        registry = MetricRegistry()
        registry.discover()
        all_names = registry.list_all()
        assert isinstance(all_names, list)

    def test_discover_finds_all_builtins(self) -> None:
        registry = MetricRegistry()
        registry.discover()
        names = registry.list_all()
        expected = [
            "accuracy",
            "auc",
            "cohens_d",
            "f1",
            "mae",
            "precision",
            "r2",
            "recall",
            "rmse",
        ]
        assert names == expected

    def test_register_overwrites_same_name(self) -> None:
        registry = MetricRegistry()
        metric1 = DummyMetric()
        metric2 = DummyMetric()
        registry.register(metric1)
        registry.register(metric2)
        assert registry.get("dummy") is metric2
