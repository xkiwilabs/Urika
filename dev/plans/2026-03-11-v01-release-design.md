# v0.1 Release Readiness Design

**Date**: 2026-03-11
**Status**: Approved
**Context**: Get Urika to a state where it can be installed and tested on a real problem.

---

## 1. New Methods (5)

All follow existing `IAnalysisMethod` pattern with `get_method()` factory in `src/urika/methods/`.

| Method | Category | Implementation |
|--------|----------|---------------|
| `logistic_regression` | classification | sklearn `LogisticRegression`, metrics: accuracy, f1, precision, recall |
| `xgboost_regression` | regression | sklearn `GradientBoostingRegressor`, metrics: r2, rmse, mae |
| `descriptive_stats` | statistics | pandas describe + scipy skew/kurtosis, metrics: n_rows, n_columns |
| `one_way_anova` | statistical_test | scipy `f_oneway`, params: group_column, value_column, metrics: f_statistic, p_value |
| `mann_whitney_u` | statistical_test | scipy `mannwhitneyu`, params: column_a, column_b, metrics: u_statistic, p_value |

## 2. New Tools (3)

All follow existing `ITool` pattern with `get_tool()` factory in `src/urika/tools/`.

| Tool | Category | Implementation |
|------|----------|---------------|
| `visualization` | exploration | matplotlib histogram/scatter/boxplot, saves PNGs to artifacts/ |
| `hypothesis_tests` | statistics | t-test, chi-squared, Shapiro-Wilk normality test |
| `outlier_detection` | exploration | IQR + z-score methods, returns flagged indices + counts |

## 3. CLI Commands (2)

| Command | What |
|---------|------|
| `urika inspect <project> [--data FILE]` | Load dataset, print schema, dtypes, missing counts, row count, first 5 rows |
| `urika logs <project> [--experiment ID]` | Print turn-by-turn log from session + progress data |

## 4. Documentation

| File | Content |
|------|---------|
| `README.md` | Installation, quickstart, CLI reference, project structure |
| `CLAUDE.md` | Update test count, module list, completed features |

## 5. File Changes

| Action | File |
|--------|------|
| Create | `src/urika/methods/logistic_regression.py` |
| Create | `src/urika/methods/xgboost_regression.py` |
| Create | `src/urika/methods/descriptive_stats.py` |
| Create | `src/urika/methods/one_way_anova.py` |
| Create | `src/urika/methods/mann_whitney_u.py` |
| Create | `src/urika/tools/visualization.py` |
| Create | `src/urika/tools/hypothesis_tests.py` |
| Create | `src/urika/tools/outlier_detection.py` |
| Create | `tests/test_methods/test_logistic_regression.py` |
| Create | `tests/test_methods/test_xgboost_regression.py` |
| Create | `tests/test_methods/test_descriptive_stats.py` |
| Create | `tests/test_methods/test_one_way_anova.py` |
| Create | `tests/test_methods/test_mann_whitney_u.py` |
| Create | `tests/test_tools/test_visualization.py` |
| Create | `tests/test_tools/test_hypothesis_tests.py` |
| Create | `tests/test_tools/test_outlier_detection.py` |
| Modify | `src/urika/cli.py` |
| Modify | `tests/test_cli.py` |
| Create | `README.md` |
| Modify | `CLAUDE.md` |

No new dependencies — all use numpy, scipy, pandas, scikit-learn, matplotlib (already in deps or stdlib).
