"""Unified dataset loading with format auto-detection."""

from __future__ import annotations

from pathlib import Path

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.data.readers.registry import ReaderRegistry


def load_dataset(path: Path, name: str | None = None) -> DatasetView:
    """Load a dataset, auto-detecting format by extension.

    Args:
        path: Path to the data file.
        name: Human-friendly name. Defaults to the filename stem.

    Returns:
        A DatasetView with the loaded data and profiling summary.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file extension is not supported by any reader.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    registry = ReaderRegistry()
    registry.discover()

    reader = registry.get_by_extension(ext)
    if reader is None:
        raise ValueError(f"Unsupported file format: '{ext}'")

    df = reader.read(path)
    summary = profile_dataset(df)
    spec = DatasetSpec(path=path, format=reader.name(), name=name or path.stem)

    return DatasetView(spec=spec, data=df, summary=summary)


def load_dataset_directory(
    path: Path,
    pattern: str = "*.csv",
    name: str | None = None,
) -> DatasetView:
    """Load all matching files in a directory into a single DataFrame.

    Adds a '_source_file' column with the relative path of each source file.

    Args:
        path: Path to the directory containing data files.
        pattern: Glob pattern to match files. Defaults to ``*.csv``.
        name: Human-friendly name. Defaults to the directory name.

    Returns:
        A DatasetView with the concatenated data and profiling summary.

    Raises:
        FileNotFoundError: If the directory does not exist.
        ValueError: If no files match the pattern.
    """
    import pandas as pd

    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")

    files = sorted(path.glob(pattern))
    if not files:
        raise ValueError(f"No files found matching '{pattern}' in {path}")

    frames: list[pd.DataFrame] = []
    for f in files:
        df = pd.read_csv(f)
        df["_source_file"] = str(f.relative_to(path))
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    summary = profile_dataset(combined)
    spec = DatasetSpec(path=path, format="csv_directory", name=name or path.name)

    return DatasetView(spec=spec, data=combined, summary=summary)
