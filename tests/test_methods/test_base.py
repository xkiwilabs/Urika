"""Tests for IAnalysisMethod ABC and MethodResult."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from urika.data.models import DatasetSpec, DataSummary, DatasetView
from urika.methods.base import IAnalysisMethod, MethodResult


class DummyMethod(IAnalysisMethod):
    """Concrete method for testing."""

    def name(self) -> str:
        return "dummy"

    def description(self) -> str:
        return "A dummy method for testing"

    def category(self) -> str:
        return "test"

    def default_params(self) -> dict[str, Any]:
        return {"alpha": 0.1}

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        return MethodResult(
            metrics={"r2": 0.85, "rmse": 0.12},
            artifacts=["output.csv"],
        )


class TestMethodResult:
    def test_create_with_required_fields(self) -> None:
        result = MethodResult(metrics={"r2": 0.9}, artifacts=[])
        assert result.metrics == {"r2": 0.9}
        assert result.artifacts == []
        assert result.valid is True
        assert result.error is None

    def test_create_with_failure(self) -> None:
        result = MethodResult(
            metrics={},
            artifacts=[],
            valid=False,
            error="Division by zero",
        )
        assert result.valid is False
        assert result.error == "Division by zero"

    def test_create_with_artifacts(self) -> None:
        result = MethodResult(
            metrics={"f1": 0.88},
            artifacts=["plot.png", "predictions.csv"],
        )
        assert len(result.artifacts) == 2


class TestIAnalysisMethod:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            IAnalysisMethod()  # type: ignore[abstract]

    def test_concrete_implementation_metadata(self) -> None:
        method = DummyMethod()
        assert method.name() == "dummy"
        assert method.description() == "A dummy method for testing"
        assert method.category() == "test"

    def test_default_params(self) -> None:
        method = DummyMethod()
        params = method.default_params()
        assert params == {"alpha": 0.1}

    def test_run_returns_method_result(self) -> None:
        method = DummyMethod()
        data = DatasetView(
            spec=DatasetSpec(path=Path("/tmp/test.csv"), format="csv"),
            data=pd.DataFrame({"x": [1, 2, 3]}),
            summary=DataSummary(
                n_rows=3,
                n_columns=1,
                columns=["x"],
                dtypes={"x": "int64"},
                missing_counts={"x": 0},
                numeric_stats={
                    "x": {
                        "mean": 2.0,
                        "std": 1.0,
                        "min": 1.0,
                        "max": 3.0,
                        "median": 2.0,
                    }
                },
            ),
        )
        result = method.run(data, {"alpha": 0.1})
        assert isinstance(result, MethodResult)
        assert result.metrics["r2"] == 0.85
        assert result.valid is True
