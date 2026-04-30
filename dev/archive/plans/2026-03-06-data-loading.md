# Data Loading Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pluggable data loading system with CSV reader and basic profiling.

**Architecture:** `IDataReader` ABC + `ReaderRegistry` (same auto-discovery pattern as `MetricRegistry` and `AgentRegistry`). A unified `load_dataset()` entry point auto-detects format by extension, reads via the matching reader, profiles the result, and returns a `DatasetView` containing the DataFrame + profiling stats.

**Tech Stack:** `pandas` (new dependency), `pytest`, existing registry patterns.

**Design doc:** `docs/plans/2026-03-06-data-loading-design.md`

---

### Task 1: Add pandas dependency and create package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/urika/data/__init__.py`
- Create: `src/urika/data/readers/__init__.py`

**Step 1: Add pandas to dependencies in `pyproject.toml`**

In the `[project]` section, add `"pandas>=2.0"` to the `dependencies` list:

```toml
dependencies = [
    "click>=8.0",
    "numpy>=1.24",
    "pandas>=2.0",
    "scikit-learn>=1.3",
]
```

**Step 2: Create empty package files**

Create `src/urika/data/__init__.py` — empty file.
Create `src/urika/data/readers/__init__.py` — empty file.

**Step 3: Reinstall and verify**

Run: `pip install -e ".[dev]"`
Expected: Installs successfully with pandas.

Run: `python -c "import urika.data; import urika.data.readers; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml src/urika/data/__init__.py src/urika/data/readers/__init__.py
git commit -m "feat(data): add pandas dependency and data package skeleton"
```

---

### Task 2: Data models (DatasetSpec, DataSummary, DatasetView)

**Files:**
- Create: `src/urika/data/models.py`
- Create: `tests/test_data/__init__.py`
- Create: `tests/test_data/test_models.py`

**Step 1: Write the failing tests**

Create `tests/test_data/__init__.py` — empty file.

Create `tests/test_data/test_models.py`:

```python
"""Tests for data models."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


class TestDatasetSpec:
    """Test DatasetSpec dataclass."""

    def test_create_with_required_fields(self) -> None:
        from urika.data.models import DatasetSpec

        spec = DatasetSpec(path=Path("/tmp/data.csv"), format="csv")
        assert spec.path == Path("/tmp/data.csv")
        assert spec.format == "csv"
        assert spec.name is None

    def test_create_with_name(self) -> None:
        from urika.data.models import DatasetSpec

        spec = DatasetSpec(path=Path("/tmp/data.csv"), format="csv", name="my_data")
        assert spec.name == "my_data"


class TestDataSummary:
    """Test DataSummary dataclass."""

    def test_create_with_all_fields(self) -> None:
        from urika.data.models import DataSummary

        summary = DataSummary(
            n_rows=100,
            n_columns=3,
            columns=["a", "b", "c"],
            dtypes={"a": "int64", "b": "float64", "c": "object"},
            missing_counts={"a": 0, "b": 5, "c": 2},
            numeric_stats={
                "a": {"mean": 50.0, "std": 10.0, "min": 1.0, "max": 100.0, "median": 50.0},
                "b": {"mean": 3.14, "std": 1.0, "min": 0.0, "max": 6.28, "median": 3.14},
            },
        )
        assert summary.n_rows == 100
        assert summary.n_columns == 3
        assert len(summary.columns) == 3
        assert summary.dtypes["a"] == "int64"
        assert summary.missing_counts["b"] == 5
        assert "c" not in summary.numeric_stats  # non-numeric excluded

    def test_numeric_stats_empty_for_no_numeric_columns(self) -> None:
        from urika.data.models import DataSummary

        summary = DataSummary(
            n_rows=10,
            n_columns=1,
            columns=["name"],
            dtypes={"name": "object"},
            missing_counts={"name": 0},
            numeric_stats={},
        )
        assert summary.numeric_stats == {}


class TestDatasetView:
    """Test DatasetView dataclass."""

    def test_create_with_all_fields(self) -> None:
        from urika.data.models import DatasetSpec, DataSummary, DatasetView

        spec = DatasetSpec(path=Path("/tmp/data.csv"), format="csv")
        df = pd.DataFrame({"a": [1, 2, 3]})
        summary = DataSummary(
            n_rows=3,
            n_columns=1,
            columns=["a"],
            dtypes={"a": "int64"},
            missing_counts={"a": 0},
            numeric_stats={"a": {"mean": 2.0, "std": 1.0, "min": 1.0, "max": 3.0, "median": 2.0}},
        )
        view = DatasetView(spec=spec, data=df, summary=summary)
        assert view.spec is spec
        assert len(view.data) == 3
        assert view.summary.n_rows == 3
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.data.models'`

**Step 3: Write minimal implementation**

Create `src/urika/data/models.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_models.py -v`
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add src/urika/data/models.py tests/test_data/__init__.py tests/test_data/test_models.py
git commit -m "feat(data): add DatasetSpec, DataSummary, DatasetView models"
```

---

### Task 3: IDataReader ABC and ReaderRegistry

**Files:**
- Create: `src/urika/data/readers/base.py`
- Create: `src/urika/data/readers/registry.py`
- Create: `tests/test_data/test_readers/__init__.py`
- Create: `tests/test_data/test_readers/test_registry.py`

**Step 1: Write the failing tests**

Create `tests/test_data/test_readers/__init__.py` — empty file.

Create `tests/test_data/test_readers/test_registry.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data/test_readers/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.data.readers.base'`

**Step 3: Write minimal implementation**

Create `src/urika/data/readers/base.py`:

```python
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
```

Create `src/urika/data/readers/registry.py`:

```python
"""Reader registry with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil

from urika.data.readers.base import IDataReader


class ReaderRegistry:
    """Registry for data readers with auto-discovery by extension."""

    def __init__(self) -> None:
        self._readers: dict[str, IDataReader] = {}  # name -> reader
        self._extensions: dict[str, IDataReader] = {}  # ext -> reader

    def register(self, reader: IDataReader) -> None:
        """Register a reader, mapping all its extensions."""
        self._readers[reader.name()] = reader
        for ext in reader.supported_extensions():
            self._extensions[ext] = reader

    def get_by_extension(self, ext: str) -> IDataReader | None:
        """Get a reader by file extension, or None if unsupported."""
        return self._extensions.get(ext)

    def list_all(self) -> list[str]:
        """Return a sorted list of all registered reader names."""
        return sorted(self._readers.keys())

    def discover(self) -> None:
        """Auto-discover readers from readers/ submodules with get_reader()."""
        import urika.data.readers as readers_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(readers_pkg.__path__):
            if modname in ("base", "registry"):
                continue
            module = importlib.import_module(f"urika.data.readers.{modname}")
            get_reader = getattr(module, "get_reader", None)
            if callable(get_reader):
                reader = get_reader()
                if isinstance(reader, IDataReader):
                    self.register(reader)
```

**Step 4: Run tests to verify they pass (except discover tests — no csv_reader yet)**

Run: `pytest tests/test_data/test_readers/test_registry.py -v -k "not discover"`
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add src/urika/data/readers/base.py src/urika/data/readers/registry.py \
    tests/test_data/test_readers/__init__.py tests/test_data/test_readers/test_registry.py
git commit -m "feat(data): add IDataReader ABC and ReaderRegistry"
```

---

### Task 4: CSV reader

**Files:**
- Create: `src/urika/data/readers/csv_reader.py`
- Create: `tests/test_data/test_readers/test_csv_reader.py`

**Step 1: Write the failing tests**

Create `tests/test_data/test_readers/test_csv_reader.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data/test_readers/test_csv_reader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.data.readers.csv_reader'`

**Step 3: Write minimal implementation**

Create `src/urika/data/readers/csv_reader.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_readers/test_csv_reader.py -v`
Expected: 8 PASSED

Now verify the discover tests from Task 3 also pass:

Run: `pytest tests/test_data/test_readers/test_registry.py -v`
Expected: 9 PASSED (all including discover tests)

**Step 5: Commit**

```bash
git add src/urika/data/readers/csv_reader.py tests/test_data/test_readers/test_csv_reader.py
git commit -m "feat(data): add CSV reader with auto-discovery"
```

---

### Task 5: Dataset profiler

**Files:**
- Create: `src/urika/data/profiler.py`
- Create: `tests/test_data/test_profiler.py`

**Step 1: Write the failing tests**

Create `tests/test_data/test_profiler.py`:

```python
"""Tests for dataset profiler."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from urika.data.models import DataSummary
from urika.data.profiler import profile_dataset


class TestProfileDataset:
    """Test the profile_dataset function."""

    def test_returns_data_summary(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = profile_dataset(df)
        assert isinstance(result, DataSummary)

    def test_row_and_column_counts(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": ["x", "y"]})
        result = profile_dataset(df)
        assert result.n_rows == 2
        assert result.n_columns == 3

    def test_column_names(self) -> None:
        df = pd.DataFrame({"alpha": [1], "beta": [2]})
        result = profile_dataset(df)
        assert result.columns == ["alpha", "beta"]

    def test_dtypes(self) -> None:
        df = pd.DataFrame({"a": [1, 2], "b": [1.0, 2.0], "c": ["x", "y"]})
        result = profile_dataset(df)
        assert result.dtypes["a"] == "int64"
        assert result.dtypes["b"] == "float64"
        assert result.dtypes["c"] == "object"

    def test_missing_counts(self) -> None:
        df = pd.DataFrame({"a": [1, None, 3], "b": [None, None, "x"]})
        result = profile_dataset(df)
        assert result.missing_counts["a"] == 1
        assert result.missing_counts["b"] == 2

    def test_missing_counts_zero_when_complete(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = profile_dataset(df)
        assert result.missing_counts["a"] == 0

    def test_numeric_stats_for_numeric_columns(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0]})
        result = profile_dataset(df)
        stats = result.numeric_stats["a"]
        assert stats["mean"] == pytest.approx(3.0)
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(5.0)
        assert stats["median"] == pytest.approx(3.0)
        assert "std" in stats

    def test_numeric_stats_excludes_non_numeric(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result = profile_dataset(df)
        assert "a" in result.numeric_stats
        assert "b" not in result.numeric_stats

    def test_numeric_stats_empty_for_all_non_numeric(self) -> None:
        df = pd.DataFrame({"name": ["alice", "bob"]})
        result = profile_dataset(df)
        assert result.numeric_stats == {}

    def test_numeric_stats_handles_missing_values(self) -> None:
        df = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        result = profile_dataset(df)
        stats = result.numeric_stats["a"]
        assert stats["mean"] == pytest.approx(2.0)
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(3.0)

    def test_empty_dataframe(self) -> None:
        df = pd.DataFrame()
        result = profile_dataset(df)
        assert result.n_rows == 0
        assert result.n_columns == 0
        assert result.columns == []
        assert result.numeric_stats == {}
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data/test_profiler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.data.profiler'`

**Step 3: Write minimal implementation**

Create `src/urika/data/profiler.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_profiler.py -v`
Expected: 11 PASSED

**Step 5: Commit**

```bash
git add src/urika/data/profiler.py tests/test_data/test_profiler.py
git commit -m "feat(data): add dataset profiler"
```

---

### Task 6: Unified loader (load_dataset)

**Files:**
- Create: `src/urika/data/loader.py`
- Create: `tests/test_data/test_loader.py`

**Step 1: Write the failing tests**

Create `tests/test_data/test_loader.py`:

```python
"""Tests for unified dataset loader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.data.loader import load_dataset
from urika.data.models import DatasetView


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    """Create a simple CSV file."""
    p = tmp_path / "sample.csv"
    p.write_text("x,y,label\n1,2.0,a\n3,4.0,b\n5,6.0,c\n")
    return p


class TestLoadDataset:
    """Test the load_dataset function."""

    def test_returns_dataset_view(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert isinstance(view, DatasetView)

    def test_spec_has_correct_path(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.spec.path == csv_file

    def test_spec_has_correct_format(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.spec.format == "csv"

    def test_spec_name_defaults_to_stem(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.spec.name == "sample"

    def test_spec_name_can_be_overridden(self, csv_file: Path) -> None:
        view = load_dataset(csv_file, name="my_data")
        assert view.spec.name == "my_data"

    def test_data_is_dataframe(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert isinstance(view.data, pd.DataFrame)

    def test_data_has_correct_shape(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.data.shape == (3, 3)

    def test_summary_is_populated(self, csv_file: Path) -> None:
        view = load_dataset(csv_file)
        assert view.summary.n_rows == 3
        assert view.summary.n_columns == 3
        assert "x" in view.summary.numeric_stats

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xyz"
        p.write_text("some data")
        with pytest.raises(ValueError, match="Unsupported file format"):
            load_dataset(p)

    def test_nonexistent_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_dataset(tmp_path / "missing.csv")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.data.loader'`

**Step 3: Write minimal implementation**

Create `src/urika/data/loader.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_loader.py -v`
Expected: 10 PASSED

**Step 5: Commit**

```bash
git add src/urika/data/loader.py tests/test_data/test_loader.py
git commit -m "feat(data): add unified load_dataset with auto-detection and profiling"
```

---

### Task 7: Public API exports

**Files:**
- Modify: `src/urika/data/__init__.py`
- Create: `tests/test_data/test_public_api.py`

**Step 1: Write the failing tests**

Create `tests/test_data/test_public_api.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'DatasetSpec' from 'urika.data'`

**Step 3: Write implementation**

Update `src/urika/data/__init__.py`:

```python
"""Data loading and profiling."""

from urika.data.loader import load_dataset
from urika.data.models import DatasetSpec, DatasetView, DataSummary
from urika.data.profiler import profile_dataset
from urika.data.readers.base import IDataReader
from urika.data.readers.registry import ReaderRegistry

__all__ = [
    "DatasetSpec",
    "DataSummary",
    "DatasetView",
    "IDataReader",
    "ReaderRegistry",
    "load_dataset",
    "profile_dataset",
]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data/test_public_api.py -v`
Expected: 7 PASSED

**Step 5: Run full test suite**

Run: `pytest -v`
Expected: All tests pass (185 existing + ~50 new)

**Step 6: Run linting**

Run: `ruff check src/urika/data/ tests/test_data/`
Run: `ruff format --check src/urika/data/ tests/test_data/`

Fix any issues if needed.

**Step 7: Commit**

```bash
git add src/urika/data/__init__.py tests/test_data/test_public_api.py
git commit -m "feat(data): add public API exports for data package"
```
