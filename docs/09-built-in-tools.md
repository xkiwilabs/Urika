# Built-in Tools

Tools are the atomic building blocks that agents use during experiments. They are distinct from **methods** -- a method is an analytical pipeline that an agent designs and executes (often composing multiple tools together), while a tool is a single, reusable computation unit that takes data in and produces structured results.

Agents do not call tools directly. The task agent writes Python code that imports and invokes tools, and the orchestrator captures the `ToolResult` output to record metrics and observations.


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
registry.discover()           # Auto-discover all 18 built-in tools
registry.list_all()           # Sorted list of tool names
registry.list_by_category("regression")  # Filter by category
registry.get("linear_regression")        # Get a specific tool
```

Each tool module exports a `get_tool()` factory function that the registry calls during auto-discovery.


## Built-in Tools by Category

Urika ships with 18 built-in tools organized into five categories.

### Exploration

Tools for understanding the data before modelling.

#### data_profiler

Profile a dataset: row/column counts, dtypes, missing data counts, and numeric summary statistics (mean, std, min, max, quartiles).

| Property | Value |
|----------|-------|
| Category | `exploration` |
| Params | None required |
| Outputs | `n_rows`, `n_columns`, `columns`, `dtypes`, `missing_counts`, `numeric_stats` |

Agents typically run this first to understand the shape and quality of the data.

---

#### correlation_analysis

Compute pairwise correlations across all numeric columns and rank the strongest relationships by absolute correlation value.

| Property | Value |
|----------|-------|
| Category | `exploration` |
| Params | `method` (default: `"pearson"`) |
| Outputs | `correlation_matrix`, `top_correlations` (sorted by abs value) |

Agents use this to identify which features are strongly related to the target variable, and to detect multicollinearity before fitting models.

---

#### outlier_detection

Detect outliers using IQR or z-score methods across selected numeric columns.

| Property | Value |
|----------|-------|
| Category | `exploration` |
| Params | `method` (`"iqr"` or `"zscore"`), `columns` (list or None for all), `threshold` (default: 1.5 for IQR, 3.0 for z-score) |
| Outputs | `outlier_counts` (per column), `total_outliers`, `n_rows`, `outlier_indices` |

Agents use this during data exploration to decide whether to remove, cap, or investigate extreme values.

---

#### visualization

Create histogram, scatter, and boxplot visualizations. Saves plots as PNG files to the specified output directory.

| Property | Value |
|----------|-------|
| Category | `exploration` |
| Params | `plot_type` (`"histogram"`, `"scatter"`, `"boxplot"`), `columns` (list), `output_dir` (default: `"artifacts"`) |
| Outputs | `plot_paths` (list of saved file paths) |
| Artifacts | PNG plot files |

Scatter plots require exactly 2 columns. Requires `matplotlib` (install with `pip install -e ".[viz]"`).

---

### Statistics

Tools for descriptive analysis and hypothesis testing.

#### descriptive_stats

Compute descriptive statistics for numeric columns: mean, standard deviation, skewness, and kurtosis (via scipy).

| Property | Value |
|----------|-------|
| Category | `statistics` |
| Params | `columns` (list or None for all numeric) |
| Metrics | `n_rows`, `n_columns` |
| Artifacts | Per-column stat summaries as text lines |

---

#### hypothesis_tests

Run statistical hypothesis tests. Supports three test types:

- **t_test** -- independent samples t-test (requires `column_a`, `column_b`)
- **chi_squared** -- chi-squared test of independence (requires `column_a`, `column_b`)
- **normality** -- Shapiro-Wilk normality test (requires `column`)

| Property | Value |
|----------|-------|
| Category | `statistics` |
| Params | `test_type`, `column_a`, `column_b`, `column` |
| Outputs | Test-specific: `t_statistic`/`p_value`, `chi2`/`p_value`/`dof`, or `w_statistic`/`p_value` |

---

#### paired_t_test

Paired t-test for comparing two related samples (e.g., pre/post measurements on the same participants). Uses `scipy.stats.ttest_rel`.

| Property | Value |
|----------|-------|
| Category | `statistical_test` |
| Params | `column_a`, `column_b` |
| Metrics | `t_statistic`, `p_value` |

---

#### one_way_anova

One-way ANOVA for comparing means across groups. Groups are defined by a categorical column; the test is run on a numeric value column using `scipy.stats.f_oneway`.

| Property | Value |
|----------|-------|
| Category | `statistical_test` |
| Params | `group_column`, `value_column` |
| Metrics | `f_statistic`, `p_value` |

Requires at least 2 groups, each with at least 2 observations.

---

#### mann_whitney_u

Mann-Whitney U test for comparing two independent samples when normality cannot be assumed. Non-parametric alternative to the independent t-test.

| Property | Value |
|----------|-------|
| Category | `statistical_test` |
| Params | `column_a`, `column_b` |
| Metrics | `u_statistic`, `p_value` |

---

### Preprocessing

Tools for splitting and transforming data before model fitting.

#### feature_scaler

Scale numeric features using standard (z-score), min-max, or robust scaling. Supports selecting specific columns or scaling all numeric columns.

| Property | Value |
|----------|-------|
| Category | `preprocessing` |
| Params | `method` (default: `"standard"`, options: `"standard"`, `"minmax"`, `"robust"`), `columns` (list or None for all numeric) |
| Outputs | `scaled_columns`, `scaler_type`, `statistics` (per-column mean/std, min/max, or center/scale depending on method) |

---

#### train_val_test_split

Split a dataset into train, optional validation, and test sets using scikit-learn. Supports stratified splitting by a target column.

| Property | Value |
|----------|-------|
| Category | `preprocessing` |
| Params | `test_size` (default: 0.2), `val_size` (default: 0.0), `random_state` (default: 42), `stratify_column` |
| Outputs | `train_size`, `val_size`, `test_size`, `train_indices`, `val_indices`, `test_indices` |
| Metrics | `train_fraction`, `val_fraction`, `test_fraction` |

---

#### cross_validation

Generate k-fold cross-validation splits, optionally stratified. Uses scikit-learn's `KFold` or `StratifiedKFold`.

| Property | Value |
|----------|-------|
| Category | `preprocessing` |
| Params | `n_folds` (default: 5), `random_state` (default: 42), `shuffle` (default: True), `stratify_column` |
| Outputs | `n_folds`, `folds` (list of `{fold, train_indices, test_indices, train_size, test_size}`) |
| Metrics | `n_folds`, `avg_test_size` |

---

#### group_split

Group-based splitting that keeps groups intact (e.g., all trials from one participant stay in the same split). Supports two modes:

- **logo** -- Leave-One-Group-Out cross-validation (one fold per group)
- **split** -- Random assignment of groups to train/val/test sets

| Property | Value |
|----------|-------|
| Category | `preprocessing` |
| Params | `group_column` (required), `mode` (`"logo"` or `"split"`), `test_groups`, `val_groups`, `random_state` |
| Outputs | Fold details (logo) or group assignments and indices (split) |
| Metrics | `n_groups`, split fractions |

This tool is particularly important for behavioral science data where repeated measures from the same participant must not leak between train and test sets.

---

### Regression

Tools for continuous outcome prediction.

#### linear_regression

Ordinary least-squares linear regression using scikit-learn. Fits on all numeric features (or a specified subset) and reports standard regression metrics.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `target` (required), `features` (list or None for all numeric) |
| Metrics | `r2`, `rmse`, `mae` |

---

#### random_forest

Random forest regression using scikit-learn's `RandomForestRegressor`. Handles non-linear relationships and feature interactions.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `target` (required), `features`, `n_estimators` (default: 100), `max_depth` (default: None), `random_state` (default: 42) |
| Metrics | `r2`, `rmse`, `mae` |

---

#### xgboost_regression

Gradient boosting regression using scikit-learn's `GradientBoostingRegressor`. Provides strong predictive performance with configurable learning rate and tree depth.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `target` (required), `features`, `n_estimators` (default: 100), `max_depth` (default: 3), `learning_rate` (default: 0.1) |
| Metrics | `r2`, `rmse`, `mae` |

---

### Classification

Tools for categorical outcome prediction.

#### logistic_regression

Logistic regression for binary and multiclass classification using scikit-learn. Automatically selects binary or weighted averaging for the F1 score based on the number of classes.

| Property | Value |
|----------|-------|
| Category | `classification` |
| Params | `target` (required), `features` (list or None for all numeric) |
| Metrics | `accuracy`, `f1` |

---

#### random_forest_classifier

Random forest classification using scikit-learn's `RandomForestClassifier`. Handles non-linear decision boundaries and feature interactions. Note: metrics are computed on the training set and may overestimate performance on unseen data.

| Property | Value |
|----------|-------|
| Category | `classification` |
| Params | `target` (required), `features`, `n_estimators` (default: 100), `max_depth` (default: None), `random_state` (default: 42) |
| Metrics | `accuracy`, `f1` |
| Outputs | `note` (recommendation to use cross-validation for unbiased estimates) |


## Project-Specific Tools

Beyond the 18 built-in tools, the **tool builder** agent can create project-specific tools. There are two ways to trigger this:

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
# REPL examples
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

The 18 built-in tools focus on tabular data analysis (statistics, regression, classification, preprocessing). For non-tabular data — images, audio, time series, spatial/3D, neuroimaging — agents handle things differently:

1. **Detection**: The source scanner recognises 40+ file extensions across all major research data types (CSV, HDF5, EDF, NIfTI, WAV, PNG, PLY, SPSS .sav, Stata .dta, and many more)
2. **Profiling**: During project creation, Urika profiles what it can — image dimensions, audio duration/sample rate, HDF5 structure — giving agents context about the data
3. **Tool building**: When agents need to work with a format the built-in tools don't handle, the tool builder creates a project-specific data reader or preprocessor
4. **Library installation**: Agents can `pip install` domain-specific libraries as needed (e.g., `mne` for EEG, `librosa` for audio, `nibabel` for neuroimaging, `h5py` for HDF5, `Pillow` for images, `open3d` for point clouds)

This means Urika works across scientific disciplines without shipping heavy domain dependencies. The agents adapt to whatever data you provide.

---

**Next:** [Knowledge Pipeline](10-knowledge-pipeline.md)
