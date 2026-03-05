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
