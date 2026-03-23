# Evaluation Framework Design

**Date**: 2026-03-06
**Status**: Approved
**Context**: Phase 2 of Urika — standalone evaluation module for scoring, criteria validation, and leaderboard ranking.

---

## 1. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Exploratory mode only | Confirmatory/pipeline evaluation modes added in later phases |
| Architecture | Standalone `src/urika/evaluation/` package | No imports from `urika.core`. Pure scoring library. Clean boundary for domain pack extensibility. |
| Metric system | Pluggable IMetric classes with auto-discovery | Matches xP3 pattern. Domain packs drop in new metric classes. |
| Metric signature | `compute(y_true, y_pred, **kwargs)` | Covers prediction-focused metrics. `**kwargs` escape hatch for edge cases. |
| Leaderboard | Best-per-method | One row per method name, updated only when beaten. Cleaner than all-runs. |
| Criteria format | JSON with min/max thresholds, metadata entries skipped by convention | No hardcoded skip list (xP3 improvement). Entries without min/max are metadata. |
| Built-in metrics | 9 core stats + ML metrics | R², RMSE, MAE, Accuracy, F1, Precision, Recall, AUC, Cohen's d |

---

## 2. Module Structure

```
src/urika/evaluation/
    __init__.py
    metrics/
        __init__.py
        base.py              # IMetric ABC
        registry.py          # MetricRegistry with auto-discovery
        regression.py        # R², RMSE, MAE
        classification.py    # Accuracy, F1, Precision, Recall, AUC
        effect_size.py       # Cohen's d
    criteria.py              # validate_criteria() — ported from xP3
    leaderboard.py           # update_leaderboard() — best-per-method

tests/test_evaluation/
    __init__.py
    test_metrics.py
    test_criteria.py
    test_leaderboard.py
```

No imports from `urika.core`. The evaluation package is a pure scoring library.

---

## 3. Metric System

### Interface

```python
class IMetric(ABC):
    def name(self) -> str: ...
    def compute(self, y_true, y_pred, **kwargs) -> float: ...
    def direction(self) -> str: ...  # "higher_is_better" | "lower_is_better"
```

### Registry

```python
class MetricRegistry:
    def discover() -> dict[str, IMetric]  # scans package for IMetric subclasses
    def get(name: str) -> IMetric
    def list_all() -> list[str]
```

### Built-in Metrics

| Metric | Module | Direction | Notes |
|--------|--------|-----------|-------|
| R² | regression.py | higher_is_better | Coefficient of determination |
| RMSE | regression.py | lower_is_better | Root mean squared error |
| MAE | regression.py | lower_is_better | Mean absolute error |
| Accuracy | classification.py | higher_is_better | Correct / total |
| F1 | classification.py | higher_is_better | Harmonic mean of precision/recall |
| Precision | classification.py | higher_is_better | TP / (TP + FP) |
| Recall | classification.py | higher_is_better | TP / (TP + FN) |
| AUC | classification.py | higher_is_better | Area under ROC curve |
| Cohen's d | effect_size.py | higher_is_better | Standardized effect size |

`compute()` takes numpy arrays and returns a float. Stateless, no side effects.

---

## 4. Success Criteria

### Format

```json
{
    "r2": {"min": 0.3, "description": "Minimum acceptable model fit"},
    "rmse": {"max": 0.5, "unit": "original scale"},
    "description": {"type": "metadata", "value": "Model quality criteria"}
}
```

### Validation

```python
def validate_criteria(
    metrics: dict[str, float],
    criteria: dict[str, dict]
) -> tuple[bool, list[str]]:
```

Behaviors:
- Entries with `"min"` or `"max"` keys are criteria; everything else is metadata
- Missing metrics silently skipped (allows partial evaluation)
- Returns `(all_passed, list_of_failure_messages)`
- Failure messages: `"r2: 0.25 < 0.3 (min)"`
- Agents and orchestrator both call this independently (trust model from xP3)

Stored at: `project_dir/config/success_criteria.json`

---

## 5. Leaderboard

### Function

```python
def update_leaderboard(
    project_dir: Path,
    method: str,
    metrics: dict[str, float],
    run_id: str,
    params: dict,
    *,
    primary_metric: str,
    direction: str,
    experiment_id: str = "",
) -> None:
```

### Storage

`project_dir/leaderboard.json`:

```json
{
    "updated": "2026-03-06T...",
    "primary_metric": "r2",
    "direction": "higher_is_better",
    "ranking": [
        {
            "rank": 1,
            "method": "xgboost",
            "run_id": "run-002",
            "metrics": {"r2": 0.85, "rmse": 0.07},
            "params": {"max_depth": 5},
            "experiment_id": "exp-002-tree-based"
        }
    ]
}
```

### Behaviors

- Best-per-method: only updates when new run beats current best for that method
- Sorted by primary metric (respecting direction)
- Ranks renumbered after each update
- Includes `experiment_id` for traceability

---

## 6. Integration Points

- **`core/progress.py`** stores `metrics` per run — evaluation *computes* them, progress *stores* them
- **`core/labbook.py`** reads metrics from progress for summaries — no changes needed
- **`leaderboard.json`** created empty by workspace — `update_leaderboard()` populates it
- **`config/success_criteria.json`** — written during project setup

Glue between evaluation and core happens at agent/orchestrator level (future phase).

---

## 7. Future: Statistical Model-Fit Metrics

**NOT in this phase.** Noted here so we don't forget.

The current `compute(y_true, y_pred)` signature covers prediction metrics. Statistical model-fit metrics require different inputs:

- **AIC, BIC**: need log-likelihood + parameter count
- **ICC**: need group structure
- **F-statistic, eta-squared**: need ANOVA table / group means
- **Marginal/conditional R²**: need mixed model objects

When we add confirmatory mode, introduce `IModelMetric` with a signature like `compute(model_summary: dict, **kwargs) -> float` to handle these. The two metric types coexist in the registry with different interfaces.

Candidates for future `IModelMetric`: AIC, BIC, ICC, eta-squared, partial eta-squared, Cronbach's alpha, CFI, RMSEA, marginal R², conditional R².
