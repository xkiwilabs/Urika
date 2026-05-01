# Tools Catalogue

Per-category reference for all 24 built-in tools shipped with Urika. See [Tools Overview](12a-tools-overview.md) for the seed-library philosophy, the `ITool` / `ToolResult` API, the registry, and how project-specific tools extend this set.

## Built-in Tools by Category

The seed library — Urika ships with 24 built-in tools organized into seven categories. Remember: the tool builder will extend this set whenever the project demands it.

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

Scatter plots require exactly 2 columns. Requires `matplotlib` (included in base install).

---

#### cluster_analysis

Unsupervised clustering using KMeans, DBSCAN, or HDBSCAN. KMeans partitions observations into a fixed number of clusters; DBSCAN and HDBSCAN are density-based and discover clusters of varying shapes without specifying `n_clusters` up front.

| Property | Value |
|----------|-------|
| Category | `exploration` |
| Params | `method` (`"kmeans"`, `"dbscan"`, or `"hdbscan"`), `n_clusters` (KMeans only), `eps` and `min_samples` (DBSCAN), `columns` (list or None for all numeric), `random_state` |
| Outputs | `cluster_labels`, `cluster_summary` (size and centroids per cluster), `n_clusters_found` |
| Metrics | `silhouette_score` (when at least two clusters are formed) |

Agents use this to surface latent groupings in the data, validate that supervised labels are recoverable from features, or generate cluster-id features for downstream models. HDBSCAN requires the `hdbscan` package.

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

#### gradient_boosting

Gradient boosting regression using scikit-learn's `GradientBoostingRegressor`. Provides strong predictive performance with configurable learning rate and tree depth.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `target` (required), `features`, `n_estimators` (default: 100), `max_depth` (default: 3), `learning_rate` (default: 0.1) |
| Metrics | `r2`, `rmse`, `mae` |

---

#### polynomial_regression

Polynomial regression: expands a single predictor into polynomial features (`x`, `x^2`, ..., `x^d`) and fits an OLS model on the expanded basis using scikit-learn.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `x_col` (required), `y_col` (required), `degree` (default: 2) |
| Outputs | `coefficients` (per polynomial term), `intercept`, `predictions` |
| Metrics | `r2`, `rmse`, `mae` |

Useful for capturing simple non-linear trends in a single predictor without moving to a fully non-parametric model.

---

#### regularized_regression

Regularized linear regression. Supports Ridge (L2), Lasso (L1), and ElasticNet (mixed) via scikit-learn. Penalises large coefficients to control overfitting and -- in the Lasso case -- perform feature selection.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `target` (required), `features` (list or None for all numeric), `method` (`"ridge"`, `"lasso"`, or `"elastic_net"`, default: `"ridge"`), `alpha` (default: 1.0), `l1_ratio` (ElasticNet only) |
| Outputs | `coefficients` (per feature), `intercept`, `feature_importance` (sorted by absolute coefficient) |
| Metrics | `r2`, `rmse`, `mae` |

Agents typically reach for this when there are many correlated features or the dataset is small relative to the number of predictors.

---

#### linear_mixed_model

Linear mixed-effects regression via statsmodels' `MixedLM`. Models fixed effects (population-level coefficients) alongside random effects that capture per-group variability -- essential for repeated-measures designs where observations from the same participant or session are not independent.

| Property | Value |
|----------|-------|
| Category | `regression` |
| Params | `formula` (Patsy formula, e.g. `"y ~ x1 + x2"`), `groups` (column name identifying the grouping variable, e.g. participant ID), `re_formula` (optional random-effects formula) |
| Outputs | `fixed_effects` (coefficient and standard error per term), `random_effects` (per-group BLUPs), `fit_summary` (text summary from statsmodels) |
| Metrics | `aic`, `bic`, `log_likelihood` |

A core tool for behavioral, neuroscience, and psychology data where trials are nested within participants.

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

---

### Dimensionality Reduction

Tools for projecting high-dimensional data into a lower-dimensional space while preserving structure.

#### pca

Principal Component Analysis via scikit-learn's `PCA`. Computes orthogonal components ordered by the variance they explain, and returns both the components themselves and the data projected onto them.

| Property | Value |
|----------|-------|
| Category | `dimensionality_reduction` |
| Params | `columns` (list or None for all numeric), `n_components` (default: 2) |
| Outputs | `components` (loadings per feature per component), `transformed` (projected data), `explained_variance_ratio` (per component), `cumulative_variance_ratio` |
| Metrics | `total_variance_explained`, `n_components` |

Useful for visualising clustering structure in 2D, removing collinearity before regression, or summarising large feature sets into a small number of latent dimensions.

---

### Time Series

Tools for analysing data ordered in time.

#### time_series_decomposition

Decompose a time series into trend, seasonal, and residual components using STL (default), classical additive, or classical multiplicative decomposition via statsmodels.

| Property | Value |
|----------|-------|
| Category | `time_series` |
| Params | `time_col` (required), `value_col` (required), `period` (required for additive/multiplicative; optional for STL), `method` (`"stl"`, `"additive"`, or `"multiplicative"`, default: `"stl"`) |
| Outputs | `trend`, `seasonal`, `residual` (each indexed by the time column), `method` |
| Metrics | `seasonal_strength`, `trend_strength` |

Agents use this to inspect whether a series has structural seasonality before fitting models, or to feed detrended residuals into downstream regression.


## See also

- [Tools Overview](12a-tools-overview.md)
- [Models and Privacy](13a-models-and-privacy.md)
- [CLI Reference — Agents](16d-cli-agents.md)
- [Project Structure](15-project-structure.md)
