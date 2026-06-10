"""Plain-language one-line explainers for built-in analytical methods.

Used by the labbook and README generators when the project audience is
``novice`` — each method heading gains a one-line "What this method
does" explainer so a reader with no statistics or machine-learning
background can follow the results.

Keys match the built-in tool names in :mod:`urika.tools` (the names
that appear in run records' ``method`` fields when agents use the seed
library). :func:`explain_method` also tolerates the looser method names
agents actually write (case differences, suffixes like
``random_forest_tuned``) via a fuzzy contains lookup.
"""

from __future__ import annotations

import re

_ALIASES: dict[str, str] = {
    "xgboost": "gradient_boosting",
    "lightgbm": "gradient_boosting",
    "lgbm": "gradient_boosting",
    "gbm": "gradient_boosting",
    "ols": "linear_regression",
    "anova": "one_way_anova",
    "ttest": "paired_t_test",
    "kmeans": "cluster_analysis",
    "ridge": "regularized_regression",
    "lasso": "regularized_regression",
    "elastic_net": "regularized_regression",
}

METHOD_GLOSSARY: dict[str, str] = {
    "cluster_analysis": (
        "Groups observations so members of the same cluster are more "
        "similar to each other than to the rest; useful for discovering "
        "hidden structure, but the number of clusters is a researcher "
        "choice the data cannot fully make for you."
    ),
    "correlation_analysis": (
        "Measures how strongly pairs of variables move together on a "
        "scale from -1 to +1; a quick map of linear relationships, but "
        "correlation alone never establishes causation."
    ),
    "cross_validation": (
        "Repeatedly splits the data into training and held-out folds so "
        "every observation is tested exactly once; gives a more honest "
        "estimate of real-world performance than a single train/test "
        "split."
    ),
    "data_profiler": (
        "Summarizes a dataset's shape, column types, missing values, and "
        "distributions before any modelling; the first sanity check that "
        "catches data problems early."
    ),
    "descriptive_stats": (
        "Computes means, medians, spreads, and ranges to characterize "
        "each variable; describes the sample at hand without making "
        "claims beyond it."
    ),
    "feature_scaler": (
        "Rescales features to comparable ranges (e.g., zero mean, unit "
        "variance) so variables measured in large units don't dominate "
        "models that are sensitive to scale."
    ),
    "gradient_boosting": (
        "Builds many shallow decision trees in sequence, each one "
        "correcting the errors of the previous ones; often the strongest "
        "predictor for tabular data, at some cost in interpretability."
    ),
    "group_split": (
        "Splits data so all observations from the same group (e.g., one "
        "participant) stay on the same side of the train/test divide, "
        "preventing the model from cheating by memorizing individuals."
    ),
    "hypothesis_tests": (
        "Formal statistical tests asking whether an observed effect "
        "could plausibly be chance; a small p-value means the data are "
        "surprising if there were no effect — not that the effect is "
        "large or important."
    ),
    "linear_mixed_model": (
        "A regression that adds random effects for grouped data (e.g., "
        "repeated measures from the same participant), separating "
        "within-group from between-group variation; the standard tool "
        "for nested experimental designs."
    ),
    "linear_regression": (
        "Fits a straight-line relationship between predictors and a "
        "continuous outcome; the simplest, most interpretable baseline — "
        "each coefficient reads directly as the change in outcome per "
        "unit change in a predictor."
    ),
    "logistic_regression": (
        "A linear model for yes/no outcomes that predicts the "
        "probability of class membership; coefficients translate to "
        "odds ratios, making it the interpretable baseline for "
        "classification."
    ),
    "mann_whitney_u": (
        "A rank-based test for whether two independent groups differ, "
        "without assuming the data are normally distributed; the "
        "non-parametric alternative to the two-sample t-test."
    ),
    "one_way_anova": (
        "Tests whether the means of three or more groups differ more "
        "than chance would allow; a significant result says at least one "
        "group differs, but follow-up comparisons are needed to say "
        "which."
    ),
    "outlier_detection": (
        "Flags observations that sit far from the rest of the data; "
        "outliers can be recording errors or genuine extremes, so they "
        "deserve inspection rather than automatic removal."
    ),
    "paired_t_test": (
        "Tests whether the average difference between paired "
        "measurements (e.g., before vs. after on the same subjects) is "
        "different from zero; pairing removes between-subject "
        "variability from the comparison."
    ),
    "pca": (
        "Principal Component Analysis rotates correlated variables into "
        "a smaller set of uncorrelated components ordered by how much "
        "variance they explain; great for compression and visualization, "
        "though components can be hard to interpret."
    ),
    "polynomial_regression": (
        "Linear regression on polynomial terms (x, x², x³, …) so curved "
        "relationships can be captured; flexible, but high-degree fits "
        "overfit quickly."
    ),
    "random_forest": (
        "An ensemble of decision trees that averages many noisy "
        "predictors into a robust, non-linear model; strong baseline, "
        "but does not extrapolate beyond the training range."
    ),
    "random_forest_classifier": (
        "A random forest for categorical outcomes: many decision trees "
        "vote on the class; robust to noise and non-linear interactions, "
        "with feature importances as a rough guide to what mattered."
    ),
    "regularized_regression": (
        "Linear regression with a penalty (ridge or lasso) that shrinks "
        "coefficients toward zero; trades a little bias for stability, "
        "and lasso can drop irrelevant features entirely."
    ),
    "time_series_decomposition": (
        "Splits a time series into trend, seasonal, and residual "
        "components; a descriptive first look at what drives change over "
        "time."
    ),
    "train_val_test_split": (
        "Partitions data into a training set (to fit models), a "
        "validation set (to tune them), and a test set kept untouched "
        "until the final, honest performance estimate."
    ),
    "visualization": (
        "Produces plots of distributions, relationships, and model "
        "outputs; figures are how humans audit what the numbers claim."
    ),
}


def explain_method(name: str) -> str | None:
    """Return the plain-language explainer for a method name, or None.

    Lookup is case-insensitive and tolerant of separator differences
    (``Random Forest`` → ``random_forest``). Exact matches win — so
    ``random_forest_classifier`` returns its own entry, not the
    ``random_forest`` one. Otherwise a fuzzy contains lookup applies:
    a glossary key contained in the name (or vice versa) matches, with
    the longest key winning (``random_forest_tuned`` →
    ``random_forest``). Unknown methods return ``None``.
    """
    if not name:
        return None
    key = re.sub(r"[\s\-]+", "_", name.strip().lower())
    if key in METHOD_GLOSSARY:
        return METHOD_GLOSSARY[key]
    if key in _ALIASES:
        return METHOD_GLOSSARY[_ALIASES[key]]
    candidates = [k for k in METHOD_GLOSSARY if k in key or key in k]
    if not candidates:
        return None
    return METHOD_GLOSSARY[max(candidates, key=len)]
