# Evaluation Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone evaluation module with pluggable metrics, success criteria validation, and a best-per-method leaderboard.

**Architecture:** `src/urika/evaluation/` is a self-contained scoring library with zero imports from `urika.core`. Metrics are pluggable IMetric classes auto-discovered via a registry. Criteria validation and leaderboard are pure functions operating on dicts and JSON files.

**Tech Stack:** Python 3.11+, numpy (new dependency), pytest, scikit-learn (for AUC)

**Design doc:** `docs/plans/2026-03-06-evaluation-framework-design.md`

---

### Task 1: Package Skeleton + numpy Dependency

**Files:**
- Modify: `pyproject.toml`
- Create: `src/urika/evaluation/__init__.py`
- Create: `src/urika/evaluation/metrics/__init__.py`
- Create: `tests/test_evaluation/__init__.py`

**Step 1: Add numpy and scikit-learn to dependencies**

In `pyproject.toml`, update the `dependencies` list:

```toml
dependencies = [
    "click>=8.0",
    "numpy>=1.24",
    "scikit-learn>=1.3",
]
```

**Step 2: Create package directories**

```bash
mkdir -p src/urika/evaluation/metrics
touch src/urika/evaluation/__init__.py
touch src/urika/evaluation/metrics/__init__.py
mkdir -p tests/test_evaluation
touch tests/test_evaluation/__init__.py
```

**Step 3: Reinstall package**

```bash
pip install -e ".[dev]"
```

**Step 4: Verify existing tests still pass**

Run: `pytest -v --tb=short`
Expected: All 59 existing tests PASS

**Step 5: Commit**

```bash
git add pyproject.toml src/urika/evaluation/ tests/test_evaluation/
git commit -m "feat: evaluation package skeleton with numpy/sklearn deps"
```

---

### Task 2: IMetric ABC + MetricRegistry

**Files:**
- Create: `src/urika/evaluation/metrics/base.py`
- Create: `src/urika/evaluation/metrics/registry.py`
- Create: `tests/test_evaluation/test_registry.py`

**Step 1: Write failing tests**

```python
"""Tests for the metric registry."""

import numpy as np

from urika.evaluation.metrics.base import IMetric
from urika.evaluation.metrics.registry import MetricRegistry


class _DummyMetric(IMetric):
    """A test metric for registry tests."""

    def name(self) -> str:
        return "dummy"

    def compute(self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs) -> float:
        return 0.0

    def direction(self) -> str:
        return "higher_is_better"


class TestIMetric:
    def test_interface(self) -> None:
        m = _DummyMetric()
        assert m.name() == "dummy"
        assert m.direction() == "higher_is_better"
        result = m.compute(np.array([1, 2]), np.array([1, 2]))
        assert result == 0.0


class TestMetricRegistry:
    def test_discover_finds_builtins(self) -> None:
        registry = MetricRegistry()
        registry.discover()
        names = registry.list_all()
        # Should find at least the built-in metrics once they exist
        assert isinstance(names, list)

    def test_register_and_get(self) -> None:
        registry = MetricRegistry()
        metric = _DummyMetric()
        registry.register(metric)
        retrieved = registry.get("dummy")
        assert retrieved is not None
        assert retrieved.name() == "dummy"

    def test_get_nonexistent(self) -> None:
        registry = MetricRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all(self) -> None:
        registry = MetricRegistry()
        registry.register(_DummyMetric())
        names = registry.list_all()
        assert "dummy" in names
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evaluation/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement IMetric ABC**

Create `src/urika/evaluation/metrics/base.py`:

```python
"""Base metric interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class IMetric(ABC):
    """Abstract base class for evaluation metrics.

    Subclass this to create new metrics. Each metric must define:
    - name(): unique string identifier
    - compute(y_true, y_pred): computes the metric value
    - direction(): "higher_is_better" or "lower_is_better"
    """

    @abstractmethod
    def name(self) -> str:
        """Return the metric's unique name (e.g., 'r2', 'rmse')."""

    @abstractmethod
    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        """Compute the metric from ground truth and predictions.

        Args:
            y_true: Ground truth values.
            y_pred: Predicted values.
            **kwargs: Additional metric-specific arguments.

        Returns:
            The computed metric value as a float.
        """

    @abstractmethod
    def direction(self) -> str:
        """Return 'higher_is_better' or 'lower_is_better'."""
```

**Step 4: Implement MetricRegistry**

Create `src/urika/evaluation/metrics/registry.py`:

```python
"""Metric registry with auto-discovery."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from urika.evaluation.metrics.base import IMetric


class MetricRegistry:
    """Registry for metric instances. Supports manual registration and auto-discovery."""

    def __init__(self) -> None:
        self._metrics: dict[str, IMetric] = {}

    def register(self, metric: IMetric) -> None:
        """Register a metric instance."""
        self._metrics[metric.name()] = metric

    def get(self, name: str) -> IMetric | None:
        """Get a metric by name, or None if not found."""
        return self._metrics.get(name)

    def list_all(self) -> list[str]:
        """Return all registered metric names."""
        return sorted(self._metrics.keys())

    def discover(self) -> None:
        """Auto-discover and register all IMetric subclasses in the metrics package."""
        import urika.evaluation.metrics as metrics_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(metrics_pkg.__path__):
            if modname in ("base", "registry"):
                continue
            module = importlib.import_module(f"urika.evaluation.metrics.{modname}")
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, IMetric) and obj is not IMetric:
                    instance = obj()
                    self._metrics[instance.name()] = instance
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_evaluation/test_registry.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/urika/evaluation/metrics/base.py src/urika/evaluation/metrics/registry.py tests/test_evaluation/test_registry.py
git commit -m "feat: IMetric ABC and MetricRegistry with auto-discovery"
```

---

### Task 3: Regression Metrics (R², RMSE, MAE)

**Files:**
- Create: `src/urika/evaluation/metrics/regression.py`
- Create: `tests/test_evaluation/test_metrics.py`

**Step 1: Write failing tests**

```python
"""Tests for built-in metrics."""

import numpy as np
import pytest

from urika.evaluation.metrics.regression import MAE, RMSE, R2


class TestR2:
    def test_perfect_prediction(self) -> None:
        y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        m = R2()
        assert m.compute(y, y) == pytest.approx(1.0)

    def test_known_value(self) -> None:
        y_true = np.array([3.0, -0.5, 2.0, 7.0])
        y_pred = np.array([2.5, 0.0, 2.0, 8.0])
        m = R2()
        result = m.compute(y_true, y_pred)
        assert result == pytest.approx(0.9486, abs=1e-3)

    def test_name_and_direction(self) -> None:
        m = R2()
        assert m.name() == "r2"
        assert m.direction() == "higher_is_better"


class TestRMSE:
    def test_perfect_prediction(self) -> None:
        y = np.array([1.0, 2.0, 3.0])
        m = RMSE()
        assert m.compute(y, y) == pytest.approx(0.0)

    def test_known_value(self) -> None:
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.1, 2.1, 3.1])
        m = RMSE()
        assert m.compute(y_true, y_pred) == pytest.approx(0.1, abs=1e-6)

    def test_name_and_direction(self) -> None:
        m = RMSE()
        assert m.name() == "rmse"
        assert m.direction() == "lower_is_better"


class TestMAE:
    def test_perfect_prediction(self) -> None:
        y = np.array([1.0, 2.0, 3.0])
        m = MAE()
        assert m.compute(y, y) == pytest.approx(0.0)

    def test_known_value(self) -> None:
        y_true = np.array([1.0, 2.0, 3.0])
        y_pred = np.array([1.5, 2.5, 3.5])
        m = MAE()
        assert m.compute(y_true, y_pred) == pytest.approx(0.5)

    def test_name_and_direction(self) -> None:
        m = MAE()
        assert m.name() == "mae"
        assert m.direction() == "lower_is_better"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evaluation/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement regression metrics**

Create `src/urika/evaluation/metrics/regression.py`:

```python
"""Regression metrics: R², RMSE, MAE."""

from __future__ import annotations

import numpy as np

from urika.evaluation.metrics.base import IMetric


class R2(IMetric):
    """Coefficient of determination (R²)."""

    def name(self) -> str:
        return "r2"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        if ss_tot == 0:
            return 1.0 if ss_res == 0 else 0.0
        return 1.0 - ss_res / ss_tot

    def direction(self) -> str:
        return "higher_is_better"


class RMSE(IMetric):
    """Root Mean Squared Error."""

    def name(self) -> str:
        return "rmse"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))

    def direction(self) -> str:
        return "lower_is_better"


class MAE(IMetric):
    """Mean Absolute Error."""

    def name(self) -> str:
        return "mae"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(np.mean(np.abs(y_true - y_pred)))

    def direction(self) -> str:
        return "lower_is_better"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evaluation/test_metrics.py -v`
Expected: All tests PASS

**Step 5: Verify auto-discovery picks them up**

Run: `pytest tests/test_evaluation/test_registry.py -v`
Expected: All tests PASS (discover now finds r2, rmse, mae)

**Step 6: Commit**

```bash
git add src/urika/evaluation/metrics/regression.py tests/test_evaluation/test_metrics.py
git commit -m "feat: regression metrics — R², RMSE, MAE"
```

---

### Task 4: Classification Metrics (Accuracy, F1, Precision, Recall, AUC)

**Files:**
- Create: `src/urika/evaluation/metrics/classification.py`
- Modify: `tests/test_evaluation/test_metrics.py`

**Step 1: Append failing tests to `tests/test_evaluation/test_metrics.py`**

Add these imports at the top:

```python
from urika.evaluation.metrics.classification import AUC, Accuracy, F1, Precision, Recall
```

Add these test classes:

```python
class TestAccuracy:
    def test_perfect(self) -> None:
        y = np.array([0, 1, 1, 0])
        m = Accuracy()
        assert m.compute(y, y) == pytest.approx(1.0)

    def test_known_value(self) -> None:
        y_true = np.array([0, 1, 1, 0, 1])
        y_pred = np.array([0, 1, 0, 0, 1])
        m = Accuracy()
        assert m.compute(y_true, y_pred) == pytest.approx(0.8)

    def test_name_and_direction(self) -> None:
        m = Accuracy()
        assert m.name() == "accuracy"
        assert m.direction() == "higher_is_better"


class TestF1:
    def test_perfect(self) -> None:
        y = np.array([0, 1, 1, 0])
        m = F1()
        assert m.compute(y, y) == pytest.approx(1.0)

    def test_known_value(self) -> None:
        y_true = np.array([1, 1, 1, 0, 0])
        y_pred = np.array([1, 0, 1, 0, 1])
        m = F1()
        # TP=2, FP=1, FN=1 -> P=2/3, R=2/3, F1=2/3
        assert m.compute(y_true, y_pred) == pytest.approx(2 / 3, abs=1e-6)

    def test_name_and_direction(self) -> None:
        m = F1()
        assert m.name() == "f1"
        assert m.direction() == "higher_is_better"


class TestPrecision:
    def test_known_value(self) -> None:
        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 0, 1, 0])
        m = Precision()
        # TP=1, FP=1 -> P=0.5
        assert m.compute(y_true, y_pred) == pytest.approx(0.5)

    def test_name_and_direction(self) -> None:
        m = Precision()
        assert m.name() == "precision"
        assert m.direction() == "higher_is_better"


class TestRecall:
    def test_known_value(self) -> None:
        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 0, 1, 0])
        m = Recall()
        # TP=1, FN=1 -> R=0.5
        assert m.compute(y_true, y_pred) == pytest.approx(0.5)

    def test_name_and_direction(self) -> None:
        m = Recall()
        assert m.name() == "recall"
        assert m.direction() == "higher_is_better"


class TestAUC:
    def test_perfect(self) -> None:
        y_true = np.array([0, 0, 1, 1])
        y_scores = np.array([0.1, 0.2, 0.8, 0.9])
        m = AUC()
        assert m.compute(y_true, y_scores) == pytest.approx(1.0)

    def test_random(self) -> None:
        y_true = np.array([0, 1, 0, 1])
        y_scores = np.array([0.5, 0.5, 0.5, 0.5])
        m = AUC()
        assert m.compute(y_true, y_scores) == pytest.approx(0.5)

    def test_name_and_direction(self) -> None:
        m = AUC()
        assert m.name() == "auc"
        assert m.direction() == "higher_is_better"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evaluation/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError` for classification imports

**Step 3: Implement classification metrics**

Create `src/urika/evaluation/metrics/classification.py`:

```python
"""Classification metrics: Accuracy, F1, Precision, Recall, AUC."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score

from urika.evaluation.metrics.base import IMetric


class Accuracy(IMetric):
    """Classification accuracy."""

    def name(self) -> str:
        return "accuracy"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(np.mean(y_true == y_pred))

    def direction(self) -> str:
        return "higher_is_better"


class Precision(IMetric):
    """Precision (positive predictive value)."""

    def name(self) -> str:
        return "precision"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        tp = float(np.sum((y_true == 1) & (y_pred == 1)))
        fp = float(np.sum((y_true == 0) & (y_pred == 1)))
        if tp + fp == 0:
            return 0.0
        return tp / (tp + fp)

    def direction(self) -> str:
        return "higher_is_better"


class Recall(IMetric):
    """Recall (sensitivity, true positive rate)."""

    def name(self) -> str:
        return "recall"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        tp = float(np.sum((y_true == 1) & (y_pred == 1)))
        fn = float(np.sum((y_true == 1) & (y_pred == 0)))
        if tp + fn == 0:
            return 0.0
        return tp / (tp + fn)

    def direction(self) -> str:
        return "higher_is_better"


class F1(IMetric):
    """F1 score (harmonic mean of precision and recall)."""

    def name(self) -> str:
        return "f1"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        p = Precision().compute(y_true, y_pred)
        r = Recall().compute(y_true, y_pred)
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)

    def direction(self) -> str:
        return "higher_is_better"


class AUC(IMetric):
    """Area Under the ROC Curve.

    y_pred should be probability scores, not class labels.
    """

    def name(self) -> str:
        return "auc"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        return float(roc_auc_score(y_true, y_pred))

    def direction(self) -> str:
        return "higher_is_better"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evaluation/test_metrics.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/evaluation/metrics/classification.py tests/test_evaluation/test_metrics.py
git commit -m "feat: classification metrics — Accuracy, F1, Precision, Recall, AUC"
```

---

### Task 5: Effect Size Metric (Cohen's d)

**Files:**
- Create: `src/urika/evaluation/metrics/effect_size.py`
- Modify: `tests/test_evaluation/test_metrics.py`

**Step 1: Append failing tests to `tests/test_evaluation/test_metrics.py`**

Add import:

```python
from urika.evaluation.metrics.effect_size import CohensD
```

Add test class:

```python
class TestCohensD:
    def test_identical_groups(self) -> None:
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        m = CohensD()
        assert m.compute(y_true, y_true) == pytest.approx(0.0)

    def test_known_value(self) -> None:
        group1 = np.array([2.0, 3.0, 4.0, 5.0, 6.0])
        group2 = np.array([4.0, 5.0, 6.0, 7.0, 8.0])
        m = CohensD()
        # Mean diff = 2, pooled SD ≈ 1.581 -> d ≈ 1.265
        result = m.compute(group1, group2)
        assert result == pytest.approx(1.265, abs=0.01)

    def test_name_and_direction(self) -> None:
        m = CohensD()
        assert m.name() == "cohens_d"
        assert m.direction() == "higher_is_better"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evaluation/test_metrics.py::TestCohensD -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement Cohen's d**

Create `src/urika/evaluation/metrics/effect_size.py`:

```python
"""Effect size metrics: Cohen's d."""

from __future__ import annotations

import numpy as np

from urika.evaluation.metrics.base import IMetric


class CohensD(IMetric):
    """Cohen's d — standardized mean difference between two groups.

    Unlike prediction metrics, this compares two groups (passed as y_true and y_pred)
    and returns the absolute standardized difference.
    """

    def name(self) -> str:
        return "cohens_d"

    def compute(
        self, y_true: np.ndarray, y_pred: np.ndarray, **kwargs: object
    ) -> float:
        n1, n2 = len(y_true), len(y_pred)
        var1, var2 = float(np.var(y_true, ddof=1)), float(np.var(y_pred, ddof=1))
        pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        if pooled_std == 0:
            return 0.0
        return abs(float(np.mean(y_pred)) - float(np.mean(y_true))) / pooled_std

    def direction(self) -> str:
        return "higher_is_better"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evaluation/test_metrics.py -v`
Expected: All tests PASS

**Step 5: Verify discover finds all 9 metrics**

Run this quick check:

```bash
python -c "
from urika.evaluation.metrics.registry import MetricRegistry
r = MetricRegistry()
r.discover()
print(sorted(r.list_all()))
"
```

Expected: `['accuracy', 'auc', 'cohens_d', 'f1', 'mae', 'precision', 'r2', 'recall', 'rmse']`

**Step 6: Commit**

```bash
git add src/urika/evaluation/metrics/effect_size.py tests/test_evaluation/test_metrics.py
git commit -m "feat: effect size metric — Cohen's d"
```

---

### Task 6: Success Criteria Validation

**Files:**
- Create: `src/urika/evaluation/criteria.py`
- Create: `tests/test_evaluation/test_criteria.py`

**Step 1: Write failing tests**

```python
"""Tests for success criteria validation."""

from urika.evaluation.criteria import validate_criteria


class TestValidateCriteria:
    def test_all_pass(self) -> None:
        metrics = {"r2": 0.5, "rmse": 0.3}
        criteria = {
            "r2": {"min": 0.3},
            "rmse": {"max": 0.5},
        }
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []

    def test_min_failure(self) -> None:
        metrics = {"r2": 0.2}
        criteria = {"r2": {"min": 0.3}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 1
        assert "0.2" in failures[0]
        assert "0.3" in failures[0]
        assert "min" in failures[0]

    def test_max_failure(self) -> None:
        metrics = {"rmse": 0.6}
        criteria = {"rmse": {"max": 0.5}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 1
        assert "max" in failures[0]

    def test_multiple_failures(self) -> None:
        metrics = {"r2": 0.1, "rmse": 0.9}
        criteria = {
            "r2": {"min": 0.3},
            "rmse": {"max": 0.5},
        }
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False
        assert len(failures) == 2

    def test_missing_metric_skipped(self) -> None:
        metrics = {"r2": 0.5}
        criteria = {
            "r2": {"min": 0.3},
            "rmse": {"max": 0.5},
        }
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
        assert failures == []

    def test_metadata_entries_skipped(self) -> None:
        metrics = {"r2": 0.5}
        criteria = {
            "r2": {"min": 0.3},
            "description": {"type": "metadata", "value": "Model quality"},
            "notes": "Some text",
        }
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True

    def test_empty_criteria(self) -> None:
        metrics = {"r2": 0.5}
        passed, failures = validate_criteria(metrics, {})
        assert passed is True
        assert failures == []

    def test_empty_metrics(self) -> None:
        criteria = {"r2": {"min": 0.3}}
        passed, failures = validate_criteria({}, criteria)
        assert passed is True
        assert failures == []

    def test_both_min_and_max(self) -> None:
        metrics = {"r2": 0.5}
        criteria = {"r2": {"min": 0.3, "max": 0.8}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True

    def test_both_min_and_max_fail_min(self) -> None:
        metrics = {"r2": 0.1}
        criteria = {"r2": {"min": 0.3, "max": 0.8}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is False

    def test_exact_threshold_passes(self) -> None:
        metrics = {"r2": 0.3}
        criteria = {"r2": {"min": 0.3}}
        passed, failures = validate_criteria(metrics, criteria)
        assert passed is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evaluation/test_criteria.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement criteria validation**

Create `src/urika/evaluation/criteria.py`:

```python
"""Success criteria validation."""

from __future__ import annotations

from typing import Any


def validate_criteria(
    metrics: dict[str, float],
    criteria: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Check metrics against success criteria.

    Criteria entries with "min" or "max" keys are validated.
    All other entries (metadata, descriptions) are silently skipped.
    Metrics not present in the metrics dict are silently skipped.

    Args:
        metrics: Computed metric values, e.g. {"r2": 0.5, "rmse": 0.3}.
        criteria: Success criteria spec, e.g. {"r2": {"min": 0.3}}.

    Returns:
        Tuple of (all_passed, list_of_failure_messages).
    """
    failures: list[str] = []

    for key, spec in criteria.items():
        if not isinstance(spec, dict):
            continue
        if "min" not in spec and "max" not in spec:
            continue
        if key not in metrics:
            continue

        value = metrics[key]

        if "min" in spec and value < spec["min"]:
            failures.append(f"{key}: {value} < {spec['min']} (min)")
        if "max" in spec and value > spec["max"]:
            failures.append(f"{key}: {value} > {spec['max']} (max)")

    return (len(failures) == 0, failures)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evaluation/test_criteria.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/evaluation/criteria.py tests/test_evaluation/test_criteria.py
git commit -m "feat: success criteria validation — min/max thresholds"
```

---

### Task 7: Leaderboard

**Files:**
- Create: `src/urika/evaluation/leaderboard.py`
- Create: `tests/test_evaluation/test_leaderboard.py`

**Step 1: Write failing tests**

```python
"""Tests for the leaderboard."""

import json
from pathlib import Path

import pytest

from urika.evaluation.leaderboard import load_leaderboard, update_leaderboard


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir()
    # Write initial empty leaderboard (matches workspace.py format)
    (d / "leaderboard.json").write_text(
        json.dumps({"entries": []}, indent=2) + "\n"
    )
    return d


class TestUpdateLeaderboard:
    def test_first_entry(self, project_dir: Path) -> None:
        update_leaderboard(
            project_dir,
            method="linear_regression",
            metrics={"r2": 0.72, "rmse": 0.15},
            run_id="run-001",
            params={"alpha": 0.1},
            primary_metric="r2",
            direction="higher_is_better",
            experiment_id="exp-001",
        )
        lb = load_leaderboard(project_dir)
        assert len(lb["ranking"]) == 1
        assert lb["ranking"][0]["method"] == "linear_regression"
        assert lb["ranking"][0]["rank"] == 1

    def test_better_run_updates(self, project_dir: Path) -> None:
        update_leaderboard(
            project_dir,
            method="ridge",
            metrics={"r2": 0.70},
            run_id="run-001",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        update_leaderboard(
            project_dir,
            method="ridge",
            metrics={"r2": 0.75},
            run_id="run-002",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        lb = load_leaderboard(project_dir)
        assert len(lb["ranking"]) == 1
        assert lb["ranking"][0]["run_id"] == "run-002"
        assert lb["ranking"][0]["metrics"]["r2"] == 0.75

    def test_worse_run_does_not_update(self, project_dir: Path) -> None:
        update_leaderboard(
            project_dir,
            method="ridge",
            metrics={"r2": 0.75},
            run_id="run-001",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        update_leaderboard(
            project_dir,
            method="ridge",
            metrics={"r2": 0.70},
            run_id="run-002",
            params={},
            primary_metric="r2",
            direction="higher_is_better",
        )
        lb = load_leaderboard(project_dir)
        assert lb["ranking"][0]["run_id"] == "run-001"

    def test_multiple_methods_sorted(self, project_dir: Path) -> None:
        for method, r2 in [("lasso", 0.60), ("xgboost", 0.85), ("ridge", 0.73)]:
            update_leaderboard(
                project_dir,
                method=method,
                metrics={"r2": r2},
                run_id=f"run-{method}",
                params={},
                primary_metric="r2",
                direction="higher_is_better",
            )
        lb = load_leaderboard(project_dir)
        assert len(lb["ranking"]) == 3
        assert lb["ranking"][0]["method"] == "xgboost"
        assert lb["ranking"][0]["rank"] == 1
        assert lb["ranking"][1]["method"] == "ridge"
        assert lb["ranking"][1]["rank"] == 2
        assert lb["ranking"][2]["method"] == "lasso"
        assert lb["ranking"][2]["rank"] == 3

    def test_lower_is_better(self, project_dir: Path) -> None:
        update_leaderboard(
            project_dir,
            method="model_a",
            metrics={"rmse": 0.5},
            run_id="run-a",
            params={},
            primary_metric="rmse",
            direction="lower_is_better",
        )
        update_leaderboard(
            project_dir,
            method="model_b",
            metrics={"rmse": 0.2},
            run_id="run-b",
            params={},
            primary_metric="rmse",
            direction="lower_is_better",
        )
        lb = load_leaderboard(project_dir)
        assert lb["ranking"][0]["method"] == "model_b"

    def test_stores_metadata(self, project_dir: Path) -> None:
        update_leaderboard(
            project_dir,
            method="xgboost",
            metrics={"r2": 0.85},
            run_id="run-001",
            params={"max_depth": 5},
            primary_metric="r2",
            direction="higher_is_better",
            experiment_id="exp-002",
        )
        lb = load_leaderboard(project_dir)
        entry = lb["ranking"][0]
        assert entry["params"] == {"max_depth": 5}
        assert entry["experiment_id"] == "exp-002"
        assert lb["primary_metric"] == "r2"
        assert lb["direction"] == "higher_is_better"
        assert "updated" in lb
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evaluation/test_leaderboard.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement leaderboard**

Create `src/urika/evaluation/leaderboard.py`:

```python
"""Best-per-method leaderboard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_leaderboard(project_dir: Path) -> dict[str, Any]:
    """Load the leaderboard from project_dir/leaderboard.json."""
    path = project_dir / "leaderboard.json"
    if not path.exists():
        return {"ranking": [], "updated": "", "primary_metric": "", "direction": ""}
    data = json.loads(path.read_text())
    # Handle legacy format from workspace creation
    if "ranking" not in data:
        data["ranking"] = data.pop("entries", [])
    return data


def update_leaderboard(
    project_dir: Path,
    method: str,
    metrics: dict[str, float],
    run_id: str,
    params: dict[str, Any],
    *,
    primary_metric: str,
    direction: str,
    experiment_id: str = "",
) -> None:
    """Update the leaderboard with a new run.

    Best-per-method: only updates if the new run beats the current best
    for this method on the primary metric.

    Args:
        project_dir: Project root directory.
        method: Method name (e.g., "xgboost").
        metrics: All metrics for this run.
        run_id: Unique run identifier.
        params: Method parameters used.
        primary_metric: Which metric to rank by.
        direction: "higher_is_better" or "lower_is_better".
        experiment_id: Which experiment produced this run.
    """
    data = load_leaderboard(project_dir)
    ranking = data.get("ranking", [])

    new_entry = {
        "method": method,
        "run_id": run_id,
        "metrics": metrics,
        "params": params,
        "experiment_id": experiment_id,
    }

    new_value = metrics.get(primary_metric)
    if new_value is None:
        return

    # Find existing entry for this method
    existing_idx = None
    for i, entry in enumerate(ranking):
        if entry["method"] == method:
            existing_idx = i
            break

    if existing_idx is not None:
        old_value = ranking[existing_idx]["metrics"].get(primary_metric)
        if old_value is not None:
            if direction == "higher_is_better" and new_value <= old_value:
                return
            if direction == "lower_is_better" and new_value >= old_value:
                return
        ranking[existing_idx] = new_entry
    else:
        ranking.append(new_entry)

    # Sort by primary metric
    reverse = direction == "higher_is_better"
    ranking.sort(
        key=lambda e: e["metrics"].get(primary_metric, float("-inf")),
        reverse=reverse,
    )

    # Renumber ranks
    for i, entry in enumerate(ranking):
        entry["rank"] = i + 1

    data["ranking"] = ranking
    data["updated"] = datetime.now(timezone.utc).isoformat()
    data["primary_metric"] = primary_metric
    data["direction"] = direction

    path = project_dir / "leaderboard.json"
    path.write_text(json.dumps(data, indent=2) + "\n")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evaluation/test_leaderboard.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/evaluation/leaderboard.py tests/test_evaluation/test_leaderboard.py
git commit -m "feat: best-per-method leaderboard with configurable primary metric"
```

---

### Task 8: Registry Auto-Discovery Integration Test + Final Cleanup

**Files:**
- Modify: `tests/test_evaluation/test_registry.py` (add discovery assertion)
- Modify: `src/urika/evaluation/__init__.py` (public API exports)

**Step 1: Update registry test to verify all 9 built-in metrics**

Add this test to `TestMetricRegistry` in `tests/test_evaluation/test_registry.py`:

```python
    def test_discover_finds_all_builtins(self) -> None:
        registry = MetricRegistry()
        registry.discover()
        names = registry.list_all()
        expected = [
            "accuracy", "auc", "cohens_d", "f1",
            "mae", "precision", "r2", "recall", "rmse",
        ]
        assert names == expected
```

**Step 2: Add public API to `__init__.py`**

Write `src/urika/evaluation/__init__.py`:

```python
"""Urika evaluation framework — metrics, criteria, leaderboard."""

from urika.evaluation.criteria import validate_criteria
from urika.evaluation.leaderboard import load_leaderboard, update_leaderboard
from urika.evaluation.metrics.registry import MetricRegistry

__all__ = [
    "MetricRegistry",
    "load_leaderboard",
    "update_leaderboard",
    "validate_criteria",
]
```

**Step 3: Run linter and formatter**

```bash
ruff check src/urika/evaluation/ tests/test_evaluation/
ruff format src/urika/evaluation/ tests/test_evaluation/
```

Fix any issues.

**Step 4: Run full test suite**

Run: `pytest -v --tb=short`
Expected: All tests PASS (59 existing + new evaluation tests)

**Step 5: Commit**

```bash
git add src/urika/evaluation/ tests/test_evaluation/
git commit -m "feat: evaluation public API + verify all 9 built-in metrics discovered"
```

---

## Summary

After completing all 8 tasks, the project will have:

- **IMetric ABC**: Pluggable metric interface with `name()`, `compute()`, `direction()`
- **MetricRegistry**: Auto-discovers IMetric subclasses, supports manual registration
- **9 built-in metrics**: R², RMSE, MAE, Accuracy, F1, Precision, Recall, AUC, Cohen's d
- **Criteria validation**: `validate_criteria()` checks metrics against min/max thresholds
- **Leaderboard**: Best-per-method ranking with configurable primary metric and direction
- **Zero coupling**: `urika.evaluation` has no imports from `urika.core`
- **Tests**: Full coverage of all metrics, criteria edge cases, leaderboard behaviors

This supports everything agents need: compute metrics, check success criteria, rank methods on a leaderboard.
