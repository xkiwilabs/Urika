"""Tests for dataset profiler."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from urika.data.models import DataSummary
from urika.data.profiler import profile_dataset


class TestProfileDataset:
    """Test the profile_dataset function."""

    def test_returns_data_summary(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = profile_dataset(df)
        assert isinstance(result, DataSummary)

    def test_row_and_column_counts(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": ["x", "y"]})
        result = profile_dataset(df)
        assert result.n_rows == 2
        assert result.n_columns == 3

    def test_column_names(self) -> None:
        df = pd.DataFrame({"alpha": [1], "beta": [2]})
        result = profile_dataset(df)
        assert result.columns == ["alpha", "beta"]

    def test_dtypes(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": [1.0, 2.0], "c": ["x", "y"]})
        result = profile_dataset(df)
        assert result.dtypes["a"] == "int64"
        assert result.dtypes["b"] == "float64"
        # pandas 3.0 introduced a dedicated 'str' dtype for string columns
        # that was previously reported as 'object'. Accept either so the
        # test runs cleanly across pandas 2.x and 3.x.
        assert result.dtypes["c"] in ("object", "str")

    def test_missing_counts(self) -> None:
        df = pd.DataFrame({"a": [1, None, 3], "b": [None, None, "x"]})
        result = profile_dataset(df)
        assert result.missing_counts["a"] == 1
        assert result.missing_counts["b"] == 2

    def test_missing_counts_zero_when_complete(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = profile_dataset(df)
        assert result.missing_counts["a"] == 0

    def test_numeric_stats_for_numeric_columns(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0]})
        result = profile_dataset(df)
        stats = result.numeric_stats["a"]
        assert stats["mean"] == pytest.approx(3.0)
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(5.0)
        assert stats["median"] == pytest.approx(3.0)
        assert "std" in stats

    def test_numeric_stats_excludes_non_numeric(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result = profile_dataset(df)
        assert "a" in result.numeric_stats
        assert "b" not in result.numeric_stats

    def test_numeric_stats_empty_for_all_non_numeric(self) -> None:
        df = pd.DataFrame({"name": ["alice", "bob"]})
        result = profile_dataset(df)
        assert result.numeric_stats == {}

    def test_numeric_stats_handles_missing_values(self) -> None:
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        result = profile_dataset(df)
        stats = result.numeric_stats["a"]
        assert stats["mean"] == pytest.approx(2.0)
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(3.0)

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame()
        result = profile_dataset(df)
        assert result.n_rows == 0
        assert result.n_columns == 0
        assert result.columns == []
        assert result.numeric_stats == {}


class TestProfileDatasetNonStringColumns:
    """Column *names* must come out as ``str`` even when pandas hands
    back non-string labels — a MultiIndex (tuples), integer headers, or
    list-valued labels from odd readers. Several consumers do
    ``", ".join(columns)``; pre-v0.4.4 a non-str label crashed the
    interactive project builder with ``TypeError: sequence item N:
    expected str instance, <type> found``."""

    def test_multiindex_columns_become_strings(self) -> None:
        df = pd.DataFrame(
            [[1, 2], [3, 4]],
            columns=pd.MultiIndex.from_tuples([("a", "x"), ("b", "y")]),
        )
        result = profile_dataset(df)
        assert all(isinstance(c, str) for c in result.columns)
        assert all(isinstance(k, str) for k in result.dtypes)
        assert all(isinstance(k, str) for k in result.missing_counts)
        # Must not crash a downstream join.
        ", ".join(result.columns)

    def test_integer_columns_become_strings(self) -> None:
        df = pd.DataFrame({0: [1, 2], 1: [3.0, 4.0]})
        result = profile_dataset(df)
        assert all(isinstance(c, str) for c in result.columns)
        # The numeric column's stats are keyed by the stringified name.
        assert "1" in result.numeric_stats
