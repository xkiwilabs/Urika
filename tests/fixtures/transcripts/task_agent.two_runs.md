This turn I tried two variations in one script so I could compare them
directly. Both figures are in `artifacts/`.

```json
{
  "run_id": "run-002",
  "method": "lightgbm_default",
  "params": {"n_estimators": 400, "learning_rate": 0.05, "test_size": 0.2, "random_state": 0},
  "metrics": {"r2": 0.58, "rmse": 9.94, "mae": 7.10},
  "observation": "Clear improvement over ridge — the residual structure was largely non-linear. Feature importance broadly agrees with the ridge coefficients.",
  "next_step": "Tune n_estimators / num_leaves with a small Optuna study.",
  "artifacts": ["artifacts/feature_importance_lgbm.png", "artifacts/predicted_vs_actual_lgbm.png"]
}
```

```json
{
  "run_id": "run-003",
  "method": "lightgbm_tuned",
  "params": {"n_estimators": 900, "num_leaves": 63, "learning_rate": 0.03, "test_size": 0.2, "random_state": 0},
  "metrics": {"r2": 0.63, "rmse": 9.35, "mae": 6.71},
  "observation": "Small additional gain from tuning; diminishing returns. Validation curve flattens after ~700 trees.",
  "next_step": "This looks close to the ceiling for tree models on these features; consider feature engineering.",
  "artifacts": ["artifacts/training_curve_lgbm_tuned.png", "artifacts/predicted_vs_actual_lgbm_tuned.png"]
}
```

Two runs recorded. Best so far: lightgbm_tuned (R^2=0.63).
