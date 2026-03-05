"""Tests for IDataReader ABC and ReaderRegistry."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.data.readers.base import IDataReader
from urika.data.readers.registry import ReaderRegistry


class DummyReader(IDataReader):
    """Concrete reader for testing."""

    def name(self) -> str:
        return "dummy"

    def supported_extensions(self) -> list[str]:
        return [".dum", ".dummy"]

    def read(self, path: Path) -> pd.DataFrame:
        return pd.DataFrame({"col": [1, 2, 3]})


class TestIDataReader:
    """Test the IDataReader ABC."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            IDataReader()  # type: ignore[abstract]

    def test_concrete_implementation_works(self) -> None:
        reader = DummyReader()
        assert reader.name() == "dummy"
        assert reader.supported_extensions() == [".dum", ".dummy"]

    def test_read_returns_dataframe(self) -> None:
        reader = DummyReader()
        df = reader.read(Path("/fake/path.dum"))
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3


class TestReaderRegistry:
    """Test the ReaderRegistry."""

    def test_register_and_get_by_extension(self) -> None:
        registry = ReaderRegistry()
        reader = DummyReader()
        registry.register(reader)
        assert registry.get_by_extension(".dum") is reader
        assert registry.get_by_extension(".dummy") is reader

    def test_get_unknown_extension_returns_none(self) -> None:
        registry = ReaderRegistry()
        assert registry.get_by_extension(".xyz") is None

    def test_list_all_sorted(self) -> None:
        registry = ReaderRegistry()
        registry.register(DummyReader())
        assert registry.list_all() == ["dummy"]

    def test_list_all_empty(self) -> None:
        registry = ReaderRegistry()
        assert registry.list_all() == []

    def test_discover_finds_csv_reader(self) -> None:
        """discover() should find the built-in CsvReader."""
        registry = ReaderRegistry()
        registry.discover()
        names = registry.list_all()
        assert "csv" in names

    def test_discover_maps_csv_extension(self) -> None:
        registry = ReaderRegistry()
        registry.discover()
        reader = registry.get_by_extension(".csv")
        assert reader is not None
        assert reader.name() == "csv"

    def test_register_overwrites_same_extension(self) -> None:
        registry = ReaderRegistry()
        reader1 = DummyReader()
        reader2 = DummyReader()
        registry.register(reader1)
        registry.register(reader2)
        assert registry.get_by_extension(".dum") is reader2
