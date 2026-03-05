"""Tests for data models."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


class TestDatasetSpec:
    """Test DatasetSpec dataclass."""

    def test_create_with_required_fields(self) -> None:
        from urika.data.models import DatasetSpec

        spec = DatasetSpec(path=Path("/tmp/data.csv"), format="csv")
        assert spec.path == Path("/tmp/data.csv")
        assert spec.format == "csv"
        assert spec.name is None

    def test_create_with_name(self) -> None:
        from urika.data.models import DatasetSpec

        spec = DatasetSpec(path=Path("/tmp/data.csv"), format="csv", name="my_data")
        assert spec.name == "my_data"


class TestDataSummary:
    """Test DataSummary dataclass."""

    def test_create_with_all_fields(self) -> None:
        from urika.data.models import DataSummary

        summary = DataSummary(
            n_rows=100,
            n_columns=3,
            columns=["a", "b", "c"],
            dtypes={"a": "int64", "b": "float64", "c": "object"},
            missing_counts={"a": 0, "b": 5, "c": 2},
            numeric_stats={
                "a": {"mean": 50.0, "std": 10.0, "min": 1.0, "max": 100.0, "median": 50.0},
                "b": {"mean": 3.14, "std": 1.0, "min": 0.0, "max": 6.28, "median": 3.14},
            },
        )
        assert summary.n_rows == 100
        assert summary.n_columns == 3
        assert len(summary.columns) == 3
        assert summary.dtypes["a"] == "int64"
        assert summary.missing_counts["b"] == 5
        assert "c" not in summary.numeric_stats  # non-numeric excluded

    def test_numeric_stats_empty_for_no_numeric_columns(self) -> None:
        from urika.data.models import DataSummary

        summary = DataSummary(
            n_rows=10,
            n_columns=1,
            columns=["name"],
            dtypes={"name": "object"},
            missing_counts={"name": 0},
            numeric_stats={},
        )
        assert summary.numeric_stats == {}


class TestDatasetView:
    """Test DatasetView dataclass."""

    def test_create_with_all_fields(self) -> None:
        from urika.data.models import DatasetSpec, DataSummary, DatasetView

        spec = DatasetSpec(path=Path("/tmp/data.csv"), format="csv")
        df = pd.DataFrame({"a": [1, 2, 3]})
        summary = DataSummary(
            n_rows=3,
            n_columns=1,
            columns=["a"],
            dtypes={"a": "int64"},
            missing_counts={"a": 0},
            numeric_stats={"a": {"mean": 2.0, "std": 1.0, "min": 1.0, "max": 3.0, "median": 2.0}},
        )
        view = DatasetView(spec=spec, data=df, summary=summary)
        assert view.spec is spec
        assert len(view.data) == 3
        assert view.summary.n_rows == 3
