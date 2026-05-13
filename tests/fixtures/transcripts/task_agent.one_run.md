I wrote `methods/ridge_regression_standardized.py`, ran it, and saved
the diagnostic figures to `artifacts/`. Here's what happened.

The dataset has 412 rows after dropping 6 with a missing target. I
standardized the 9 numeric features on the training fold only,
selected `alpha=2.15` via 5-fold RidgeCV, and evaluated on the 20%
held-out test fold.

```json
{
  "run_id": "run-001",
  "method": "ridge_regression_standardized",
  "params": {"alpha": 2.15, "test_size": 0.2, "random_state": 0, "cv_folds": 5},
  "metrics": {"r2": 0.41, "rmse": 11.83, "mae": 8.92},
  "hypothesis": "A standardized linear model captures the bulk of the signal as a baseline.",
  "observation": "R^2 around 0.41 — a real but modest fit. Residuals show mild heteroscedasticity at the high end; a few large under-predictions. Coefficient plot shows three features dominate.",
  "next_step": "Try a gradient-boosted regressor (lightgbm) with the same split to see how much of the residual structure is non-linear.",
  "artifacts": ["artifacts/predicted_vs_actual_ridge.png", "artifacts/residual_plot_ridge.png", "artifacts/coefficient_plot_ridge.png"]
}
```

Summary: one method tried (ridge regression, R^2=0.41 on the test
fold). Recommend a non-linear baseline next.
