# Tools Overview

The seed-library philosophy, the `ITool` interface, the `ToolResult` shape, the tool registry, and how project-specific tools extend the catalogue. See [Tools Catalogue](12b-tools-catalogue.md) for the per-category reference of all 24 built-in tools.

Tools are the atomic building blocks that agents use during experiments. They are distinct from **methods** -- a method is an analytical pipeline that an agent designs and executes (often composing multiple tools together), while a tool is a single, reusable computation unit that takes data in and produces structured results.

Agents do not call tools directly. The task agent writes Python code that imports and invokes tools, and the orchestrator captures the `ToolResult` output to record metrics and observations.

## The 24 built-ins are a starting library, not a fixed catalogue

> **Read this first.** The 24 tools listed in the [Tools Catalogue](12b-tools-catalogue.md) are a **seed library** — common-case primitives so that everyday tabular projects can produce results immediately. They are **not** the limit of what Urika can do.
>
> When a project needs a capability the built-ins don't provide, the **tool builder** agent writes a new Python tool, registers it in the project's `tools/` directory, and from that point forward it sits alongside the built-ins for the rest of the project. This is core to how Urika operates: the tool catalogue grows with the project.
>
> Two ways tool building gets triggered:
> - **Automatic** — the planning agent flags `needs_tool: true` when it identifies a gap; the tool builder runs before the next experiment.
> - **Explicit** — `urika build-tool <description>` (CLI), `/build-tool <description>` (TUI), or the **Build tool** modal in the dashboard. Use this when you know up front what tool you'll need (e.g. "create an ICC tool using pingouin", "install mne and add an EEG epoch extractor").
>
> A project working with EEG, neuroimaging, audio, time-warped trajectories, or any domain-specific feature extraction will end up with project-specific tools the agent created on demand. Project tools live at `<project>/tools/<tool_name>.py` and are discovered alongside the built-ins by the registry. See [Project-specific tools](#project-specific-tools) below.


## The ITool Interface

Every tool -- both built-in and project-specific -- implements the `ITool` abstract base class defined in `src/urika/tools/base.py`:

```python
class ITool(ABC):
    def name(self) -> str: ...
    def description(self) -> str: ...
    def category(self) -> str: ...
    def default_params(self) -> dict[str, Any]: ...
    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult: ...
```

- **name** -- unique identifier used by the registry (e.g. `"linear_regression"`)
- **description** -- human-readable summary shown to agents
- **category** -- grouping label (e.g. `"exploration"`, `"regression"`)
- **default_params** -- sensible defaults so agents can call with minimal configuration
- **run** -- executes the tool on a `DatasetView` with the given parameters


## ToolResult

Every tool returns a `ToolResult`:

```python
@dataclass
class ToolResult:
    outputs: dict[str, Any]       # Structured data (matrices, indices, stats)
    artifacts: list[str] = []     # File paths (plots, saved models)
    metrics: dict[str, float] = {} # Numeric scores (r2, p_value, rmse)
    valid: bool = True            # Whether execution succeeded
    error: str | None = None      # Error message if valid=False
```

When `valid` is `False`, the `error` field explains what went wrong (missing column, insufficient data, unsupported parameter). Agents see these errors and can adjust their approach.


## Tool Registry

The `ToolRegistry` handles discovery and lookup:

```python
from urika.tools import ToolRegistry

registry = ToolRegistry()
registry.discover()           # Auto-discover all 24 built-in tools
registry.list_all()           # Sorted list of tool names
registry.list_by_category("regression")  # Filter by category
registry.get("linear_regression")        # Get a specific tool
```

Each tool module exports a `get_tool()` factory function that the registry calls during auto-discovery.


## Project-Specific Tools

Beyond the 24 built-in tools, the **tool builder** agent can create project-specific tools. There are two ways to trigger this:

### 1. Automatically during experiments

When the planning agent identifies a need that built-in tools don't cover, it flags `needs_tool: true` and the tool builder is called automatically.

### 2. Directly via command

You can request specific tools at any time:

```bash
# Neuroscience
urika build-tool my-project "create an EEG epoch extractor using MNE"

# Statistics
urika build-tool my-project "build a tool that computes ICC using pingouin"

# Audio / speech
urika build-tool my-project "install librosa and create an audio feature extractor"

# Computer vision / motion capture
urika build-tool my-project "install mediapipe and add a tool that extracts facial pose data from video"

# NLP / text analysis
urika build-tool my-project "install sentence-transformers and build a tool that extracts word embeddings"

# Image annotation / object detection
urika build-tool my-project "install ultralytics and create a tool that detects and annotates people in images using YOLOv8"

# Genomics
urika build-tool my-project "install biopython and create a sequence alignment tool"

# Geospatial
urika build-tool my-project "install geopandas and build a spatial clustering tool"

# Climate / environmental
urika build-tool my-project "install xarray and create a NetCDF climate data loader"
```

```
# TUI examples
/build-tool create a correlation heatmap tool using seaborn
/build-tool build a data loader for our custom HDF5 format
/build-tool install spacy and create a named entity extraction tool
/build-tool install parselmouth and build a tool that extracts speech acoustics (pitch, formants)
```

You can also ask the advisor agent conversationally and it will route to the tool builder:

```
urika:my-project> I need a tool that computes inter-rater reliability
```

### Tool structure

Project-specific tools are Python files placed in the project's `tools/` directory. Each must follow the same pattern:

```python
# my_project/tools/custom_metric.py
from urika.tools.base import ITool, ToolResult

class CustomMetricTool(ITool):
    def name(self) -> str:
        return "custom_metric"

    def description(self) -> str:
        return "Project-specific metric computation."

    def category(self) -> str:
        return "custom"

    def default_params(self) -> dict[str, Any]:
        return {}

    def run(self, data, params):
        # ... implementation ...
        return ToolResult(outputs={"score": 0.95}, metrics={"score": 0.95})

def get_tool() -> ITool:
    return CustomMetricTool()
```

The registry discovers project tools via `discover_project(tools_dir)`:

```python
registry.discover_project(project_path / "tools")
```

Files starting with `_` are skipped. Each file must export a `get_tool()` function returning an `ITool` instance.

Project tools appear alongside built-in tools in the registry and are available to all agents during that project's experiments.

## Data Handling for Different Research Domains

The 24 built-in tools focus on tabular data analysis (statistics, regression, classification, preprocessing). For non-tabular data — images, audio, time series, spatial/3D, neuroimaging — agents handle things differently:

1. **Detection**: The source scanner recognises 40+ file extensions across all major research data types (CSV, HDF5, EDF, NIfTI, WAV, PNG, PLY, SPSS .sav, Stata .dta, and many more)
2. **Profiling**: During project creation, Urika profiles what it can — image dimensions, audio duration/sample rate, HDF5 structure — giving agents context about the data
3. **Tool building**: When agents need to work with a format the built-in tools don't handle, the tool builder creates a project-specific data reader or preprocessor
4. **Library installation**: Agents can `pip install` domain-specific libraries as needed (e.g., `mne` for EEG, `librosa` for audio, `nibabel` for neuroimaging, `h5py` for HDF5, `Pillow` for images, `open3d` for point clouds)

This means Urika works across scientific disciplines without shipping heavy domain dependencies. The agents adapt to whatever data you provide.


## See also

- [Tools Catalogue](12b-tools-catalogue.md)
- [Models and Privacy](13a-models-and-privacy.md)
- [CLI Reference — Agents](16d-cli-agents.md)
- [Project Structure](15-project-structure.md)
