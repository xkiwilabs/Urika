"""Data models for dataset loading and profiling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class DatasetSpec:
    """Where and what the data is."""

    path: Path
    format: str
    name: str | None = None


@dataclass
class DataSummary:
    """Profiling stats about a dataset."""

    n_rows: int
    n_columns: int
    columns: list[str]
    dtypes: dict[str, str]
    missing_counts: dict[str, int]
    numeric_stats: dict[str, dict[str, float]]


@dataclass
class DatasetView:
    """A loaded dataset with its profiling summary."""

    spec: DatasetSpec
    data: pd.DataFrame
    summary: DataSummary
