"""Base data reader interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd


class IDataReader(ABC):
    """Abstract base class for data format readers."""

    @abstractmethod
    def name(self) -> str:
        """Return the unique name of this reader."""
        ...

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return file extensions this reader handles (e.g. ['.csv'])."""
        ...

    @abstractmethod
    def read(self, path: Path) -> pd.DataFrame:
        """Read a file and return a DataFrame."""
        ...
