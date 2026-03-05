"""Tests for data package public API."""

from __future__ import annotations


class TestPublicAPI:
    """Test that key types are importable from urika.data."""

    def test_import_dataset_spec(self) -> None:
        from urika.data import DatasetSpec

        assert DatasetSpec is not None

    def test_import_dataset_summary(self) -> None:
        from urika.data import DataSummary

        assert DataSummary is not None

    def test_import_dataset_view(self) -> None:
        from urika.data import DatasetView

        assert DatasetView is not None

    def test_import_load_dataset(self) -> None:
        from urika.data import load_dataset

        assert callable(load_dataset)

    def test_import_profile_dataset(self) -> None:
        from urika.data import profile_dataset

        assert callable(profile_dataset)

    def test_import_idatareader(self) -> None:
        from urika.data import IDataReader

        assert IDataReader is not None

    def test_import_reader_registry(self) -> None:
        from urika.data import ReaderRegistry

        assert ReaderRegistry is not None
