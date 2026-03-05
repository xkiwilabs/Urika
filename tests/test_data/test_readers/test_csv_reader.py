"""Tests for CSV reader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.data.readers.csv_reader import CsvReader


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    """Create a simple CSV file for testing."""
    p = tmp_path / "test.csv"
    p.write_text("a,b,c\n1,2.0,x\n3,4.0,y\n5,,z\n")
    return p


@pytest.fixture
def reader() -> CsvReader:
    return CsvReader()


class TestCsvReader:
    """Test the CsvReader."""

    def test_name(self, reader: CsvReader) -> None:
        assert reader.name() == "csv"

    def test_supported_extensions(self, reader: CsvReader) -> None:
        assert reader.supported_extensions() == [".csv"]

    def test_read_returns_dataframe(self, reader: CsvReader, csv_file: Path) -> None:
        df = reader.read(csv_file)
        assert isinstance(df, pd.DataFrame)

    def test_read_correct_shape(self, reader: CsvReader, csv_file: Path) -> None:
        df = reader.read(csv_file)
        assert df.shape == (3, 3)

    def test_read_correct_columns(self, reader: CsvReader, csv_file: Path) -> None:
        df = reader.read(csv_file)
        assert list(df.columns) == ["a", "b", "c"]

    def test_read_preserves_missing_values(self, reader: CsvReader, csv_file: Path) -> None:
        df = reader.read(csv_file)
        assert pd.isna(df.loc[2, "b"])

    def test_read_nonexistent_file_raises(self, reader: CsvReader, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            reader.read(tmp_path / "nonexistent.csv")

    def test_get_reader_factory(self) -> None:
        from urika.data.readers.csv_reader import get_reader

        reader = get_reader()
        assert isinstance(reader, CsvReader)
