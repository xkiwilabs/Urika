"""Tests for unified dataset loader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.data.loader import load_dataset
from urika.data.models import DatasetView


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    """Create a simple CSV file."""
    p = tmp_path / "sample.csv"
    p.write_text("x,y,label\n1,2.0,a\n3,4.0,b\n5,6.0,c\n")
    return p


class TestLoadDataset:
    """Test the load_dataset function."""

    def test_returns_dataset_view(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert isinstance(view, DatasetView)

    def test_spec_has_correct_path(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.spec.path == csv_file

    def test_spec_has_correct_format(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.spec.format == "csv"

    def test_spec_name_defaults_to_stem(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.spec.name == "sample"

    def test_spec_name_can_be_overridden(self, csv_file: Path) -> None:
        view = load_dataset(csv_file, name="my_data")
        assert view.spec.name == "my_data"

    def test_data_is_dataframe(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert isinstance(view.data, pd.DataFrame)

    def test_data_has_correct_shape(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.data.shape == (3, 3)

    def test_summary_is_populated(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.summary.n_rows == 3
        assert view.summary.n_columns == 3
        assert "x" in view.summary.numeric_stats

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xyz"
        p.write_text("some data")
        with pytest.raises(ValueError, match="Unsupported file format"):
            load_dataset(p)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_dataset(tmp_path / "missing.csv")
