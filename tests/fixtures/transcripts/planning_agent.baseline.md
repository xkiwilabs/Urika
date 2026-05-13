I've looked at the project configuration and the data profile. The
research question is a straightforward predictive one, so I'll start
with a simple, well-understood baseline before reaching for anything
fancier.

```json
{
  "method_name": "ridge_regression_standardized",
  "description": "Standardize features, fit a ridge regression with a small held-out validation split, report R^2 and RMSE on the test fold.",
  "steps": [
    {"step": 1, "action": "Load the dataset and drop rows with missing target values", "tool": "data_profiler"},
    {"step": 2, "action": "Standardize numeric features (z-score) on the training fold only", "params": {}},
    {"step": 3, "action": "Fit RidgeCV over a small alpha grid using 5-fold CV on the training fold", "tool": "regularized_regression"},
    {"step": 4, "action": "Evaluate on the held-out test fold; produce a predicted-vs-actual plot and a residual plot"}
  ],
  "evaluation": {
    "strategy": "single 80/20 train/test split, RidgeCV (5-fold) for alpha selection on the training fold",
    "metrics": ["r2", "rmse"],
    "success_threshold": {}
  },
  "visualizations": ["training_validation_curves", "predicted_vs_actual", "residual_plot", "coefficient_plot"],
  "needs_tool": false,
  "tool_description": "",
  "needs_literature": false,
  "literature_query": ""
}
```

That should give us a clean reference point. If R^2 is low I'd move to
a gradient-boosted model next.
