"""Tests for IMethod ABC and MethodResult."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from urika.data.models import DatasetSpec, DataSummary, DatasetView
from urika.methods.base import IMethod, MethodResult


class DummyMethod(IMethod):
    """Concrete method for testing."""

    def name(self) -> str:
        return "dummy_pipeline"

    def description(self) -> str:
        return "A dummy pipeline for testing"

    def tools_used(self) -> list[str]:
        return ["data_profiler", "linear_regression"]

    def run(self, data: DatasetView, params: dict[str, Any]) -> MethodResult:
        return MethodResult(
            metrics={"r2": 0.85, "rmse": 0.12},
            artifacts=["output.csv"],
        )


class TestMethodResult:
    def test_create_with_required_fields(self) -> None:
        result = MethodResult(metrics={"r2": 0.9})
        assert result.metrics == {"r2": 0.9}
        assert result.artifacts == []
        assert result.valid is True
        assert result.error is None

    def test_create_with_failure(self) -> None:
        result = MethodResult(
            metrics={},
            valid=False,
            error="Pipeline failed",
        )
        assert result.valid is False
        assert result.error == "Pipeline failed"

    def test_create_with_artifacts(self) -> None:
        result = MethodResult(
            metrics={"f1": 0.88},
            artifacts=["plot.png", "predictions.csv"],
        )
        assert len(result.artifacts) == 2


class TestIMethod:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            IMethod()  # type: ignore[abstract]

    def test_concrete_implementation_metadata(self) -> None:
        method = DummyMethod()
        assert method.name() == "dummy_pipeline"
        assert method.description() == "A dummy pipeline for testing"

    def test_tools_used(self) -> None:
        method = DummyMethod()
        assert method.tools_used() == ["data_profiler", "linear_regression"]

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
        result = method.run(data, {})
        assert isinstance(result, MethodResult)
        assert result.metrics["r2"] == 0.85
        assert result.valid is True
