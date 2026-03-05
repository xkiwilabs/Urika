"""CSV file reader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from urika.data.readers.base import IDataReader


class CsvReader(IDataReader):
    """Read CSV files into DataFrames."""

    def name(self) -> str:
        return "csv"

    def supported_extensions(self) -> list[str]:
        return [".csv"]

    def read(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return pd.read_csv(path)


def get_reader() -> IDataReader:
    """Factory function for auto-discovery."""
    return CsvReader()
