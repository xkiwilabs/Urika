# Built-in Methods & Tools Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 8 of Urika — concrete implementations to prove the infrastructure end-to-end.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Methods count | 3 (linear regression, random forest, paired t-test) | Covers regression (2) + statistical testing (1). Three categories for agents to discover. |
| Tools count | 2 (data profiler, correlation analysis) | Core exploration tools agents use first when examining a dataset. |
| Train/test split | Not included — agent's responsibility | Methods score on full data. Agents configure cross-validation externally. |
| Missing data | Drop NaN rows before computation | Simple, predictable. Return valid=False if no data remains. |
| New dependency | scipy | Needed for ttest_rel in paired t-test. |

---

## 2. Module Structure

```
src/urika/methods/
    linear_regression.py     # LinearRegression method
    random_forest.py         # RandomForest method
    paired_t_test.py         # PairedTTest method

src/urika/tools/
    data_profiler.py         # DataProfiler tool
    correlation.py           # CorrelationAnalysis tool
```

Each file follows the existing factory convention (`get_method()`/`get_tool()`). Auto-discovered by existing registries — no registry code changes needed.

---

## 3. Built-in Methods

### Linear Regression

- **Module**: `linear_regression.py`, category: `"regression"`
- **Uses**: `sklearn.linear_model.LinearRegression`
- **Params**: `target` (column name), `features` (list of column names, optional — defaults to all numeric except target)
- **Metrics**: `r2`, `rmse`, `mae`
- **Handles**: drops NaN rows, returns `valid=False` if insufficient data

### Random Forest

- **Module**: `random_forest.py`, category: `"regression"`
- **Uses**: `sklearn.ensemble.RandomForestRegressor`
- **Params**: `target`, `features`, `n_estimators` (default 100), `max_depth` (default None), `random_state` (default 42)
- **Metrics**: `r2`, `rmse`, `mae`
- **Handles**: drops NaN rows, returns `valid=False` if insufficient data

### Paired T-Test

- **Module**: `paired_t_test.py`, category: `"statistical_test"`
- **Uses**: `scipy.stats.ttest_rel`
- **Params**: `column_a`, `column_b` (two column names to compare)
- **Metrics**: `t_statistic`, `p_value`
- **Handles**: returns `valid=False` if columns have different lengths, too few observations, or all NaN

---

## 4. Built-in Tools

### Data Profiler

- **Module**: `data_profiler.py`, category: `"exploration"`
- **Uses**: existing `profile_dataset()` from `urika.data.profiler`
- **Params**: none
- **Outputs**: `n_rows`, `n_columns`, `columns`, `dtypes`, `missing_counts`, `numeric_stats`
- **Handles**: returns `valid=False` if no numeric columns

### Correlation Analysis

- **Module**: `correlation.py`, category: `"exploration"`
- **Uses**: `pandas.DataFrame.corr()`
- **Params**: `method` (default `"pearson"`, also `"spearman"`, `"kendall"`)
- **Outputs**: `correlation_matrix` (dict of dicts), `top_correlations` (sorted list of strongest non-self correlations)
- **Handles**: operates on numeric columns only, drops NaN pairwise, returns `valid=False` if no numeric columns

---

## 5. Dependencies & Integration

- **New dependency**: `scipy>=1.11` added to `pyproject.toml`
- **No changes** to registry code — existing `discover()` auto-finds new modules
- **Discovery tests**: `MethodRegistry().discover()` finds 3 methods, `ToolRegistry().discover()` finds 2 tools
