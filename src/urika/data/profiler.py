"""Dataset profiling — basic statistics from a DataFrame."""

from __future__ import annotations

import pandas as pd

from urika.data.models import DataSummary


def profile_dataset(df: pd.DataFrame) -> DataSummary:
    """Generate profiling stats from a DataFrame."""
    columns = list(df.columns)
    dtypes = {col: str(df[col].dtype) for col in columns}
    missing_counts = {col: int(df[col].isna().sum()) for col in columns}

    numeric_cols = df.select_dtypes(include="number").columns
    numeric_stats: dict[str, dict[str, float]] = {}
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) == 0:
            continue
        numeric_stats[col] = {
            "mean": float(series.mean()),
            "std": float(series.std()),
            "min": float(series.min()),
            "max": float(series.max()),
            "median": float(series.median()),
        }

    return DataSummary(
        n_rows=len(df),
        n_columns=len(columns),
        columns=columns,
        dtypes=dtypes,
        missing_counts=missing_counts,
        numeric_stats=numeric_stats,
    )
