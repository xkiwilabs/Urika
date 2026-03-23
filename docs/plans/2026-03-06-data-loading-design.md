# Data Loading Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 4 of Urika — pluggable data loading with profiling.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Format scope | CSV only (this phase) | Start minimal, extensible via pluggable readers. |
| Architecture | Pluggable readers (IDataReader + ReaderRegistry) | Same auto-discovery pattern as MetricRegistry and AgentRegistry. New formats = new module, no core changes. |
| Profiling | Basic profiling on load | Row/col counts, dtypes, missing values, numeric stats. Enough for agents to understand data without manual inspection. |
| Schema inference | Deferred | Raw data + summary only. Column roles, measurement levels, and structure come in a later phase. |
| Entry point | Single `load_dataset()` function | Auto-detects format by extension, loads, profiles, returns `DatasetView`. |

---

## 2. Module Structure

```
src/urika/data/
    __init__.py              # Public API exports
    models.py                # DatasetSpec, DataSummary, DatasetView
    loader.py                # load_dataset() unified entry point
    profiler.py              # profile_dataset() generates DataSummary

    readers/
        __init__.py
        base.py              # IDataReader ABC
        registry.py          # ReaderRegistry with auto-discovery
        csv_reader.py        # CSV reader
```

---

## 3. Core Data Models

```python
# models.py

@dataclass
class DatasetSpec:
    """Where and what the data is."""
    path: Path                      # File path
    format: str                     # "csv" (extensible later)
    name: str | None = None         # Human-friendly name (defaults to filename stem)

@dataclass
class DataSummary:
    """Profiling stats about a dataset."""
    n_rows: int
    n_columns: int
    columns: list[str]
    dtypes: dict[str, str]          # column -> dtype string ("int64", "float64", "object")
    missing_counts: dict[str, int]  # column -> count of NaN/None
    numeric_stats: dict[str, dict[str, float]]  # column -> {"mean", "std", "min", "max", "median"}

@dataclass
class DatasetView:
    """A loaded dataset with its profiling summary."""
    spec: DatasetSpec
    data: pd.DataFrame              # The actual data
    summary: DataSummary            # Profiling output
```

- `DatasetSpec` is lightweight — just enough to find and identify data.
- `DataSummary` covers profiling scope: counts, dtypes, missing, basic stats.
- `DatasetView` bundles everything — this is what agents and methods receive.
- `numeric_stats` only computed for numeric columns; non-numeric columns absent from that dict.

---

## 4. Reader Interface

```python
# readers/base.py

class IDataReader(ABC):
    """Read a specific file format into a DataFrame."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def supported_extensions(self) -> list[str]: ...

    @abstractmethod
    def read(self, path: Path) -> pd.DataFrame: ...
```

```python
# readers/registry.py

class ReaderRegistry:
    """Auto-discover readers, resolve by extension."""

    def register(self, reader: IDataReader) -> None: ...
    def get_by_extension(self, ext: str) -> IDataReader | None: ...
    def list_all(self) -> list[str]: ...
    def discover(self) -> None:
        """Scan readers/ for modules with get_reader() function."""
```

```python
# readers/csv_reader.py

class CsvReader(IDataReader):
    def name(self) -> str: return "csv"
    def supported_extensions(self) -> list[str]: return [".csv"]
    def read(self, path: Path) -> pd.DataFrame:
        return pd.read_csv(path)

def get_reader() -> IDataReader:
    return CsvReader()
```

Same auto-discovery pattern as MetricRegistry and AgentRegistry — `pkgutil.iter_modules` + `get_reader()` convention.

---

## 5. Profiler

```python
# profiler.py

def profile_dataset(df: pd.DataFrame) -> DataSummary:
    """Generate profiling stats from a DataFrame."""
    # n_rows, n_columns, columns, dtypes
    # missing_counts per column
    # numeric_stats (mean, std, min, max, median) for numeric columns only
```

Pure function. Takes a DataFrame, returns a DataSummary. No side effects.

---

## 6. Unified Loader

```python
# loader.py

def load_dataset(path: Path, name: str | None = None) -> DatasetView:
    """Load a dataset file, auto-detecting format by extension."""
    # 1. Build DatasetSpec from path
    # 2. ReaderRegistry.discover() + get_by_extension()
    # 3. reader.read(path) -> DataFrame
    # 4. profile_dataset(df) -> DataSummary
    # 5. Return DatasetView(spec, data, summary)
```

Single entry point. Extension-based format detection. Profiling happens automatically on load.

---

## 7. Integration Points

- **Agents** receive `DatasetView` — DataFrame plus profiling stats.
- **Methods** call `run(data: DatasetView, ...)` — same interface as the PRD design.
- **CLI** (`urika new`) uses `load_dataset()` during project setup to validate and profile user data.
- **Future readers**: Excel, Parquet, SPSS, etc. — drop a new module in `readers/`, no changes to loader or profiler.
