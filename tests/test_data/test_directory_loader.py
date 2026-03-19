"""Tests for directory-based dataset loading."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.data.loader import load_dataset_directory


class TestLoadDatasetDirectory:
    def _make_csvs(self, tmp_path: Path, n: int = 3) -> Path:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        for i in range(n):
            df = pd.DataFrame(
                {"x": [i * 10 + j for j in range(5)], "y": [j for j in range(5)]}
            )
            df.to_csv(data_dir / f"file_{i}.csv", index=False)
        return data_dir

    def test_loads_all_csvs(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 3)
        view = load_dataset_directory(data_dir)
        assert view.summary.n_rows == 15

    def test_adds_source_file_column(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 2)
        view = load_dataset_directory(data_dir)
        assert "_source_file" in view.data.columns

    def test_pattern_filter(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 3)
        (data_dir / "notes.txt").write_text("not data")
        view = load_dataset_directory(data_dir, pattern="*.csv")
        assert view.summary.n_rows == 15

    def test_nested_glob(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        sub1 = data_dir / "group_a"
        sub2 = data_dir / "group_b"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)
        pd.DataFrame({"x": [1, 2]}).to_csv(sub1 / "f1.csv", index=False)
        pd.DataFrame({"x": [3, 4]}).to_csv(sub2 / "f2.csv", index=False)
        view = load_dataset_directory(data_dir, pattern="**/*.csv")
        assert view.summary.n_rows == 4

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError, match="No files found"):
            load_dataset_directory(empty)

    def test_nonexistent_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_dataset_directory(tmp_path / "nope")

    def test_spec_format_is_csv_directory(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 1)
        view = load_dataset_directory(data_dir)
        assert view.spec.format == "csv_directory"

    def test_returns_dataset_view(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 1)
        view = load_dataset_directory(data_dir)
        from urika.data.models import DatasetView

        assert isinstance(view, DatasetView)
