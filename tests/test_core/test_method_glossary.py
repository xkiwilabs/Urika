"""Tests for the plain-language method glossary."""

from __future__ import annotations

from urika.core.method_glossary import METHOD_GLOSSARY, explain_method


class TestGlossaryContents:
    def test_covers_builtin_tool_names(self) -> None:
        """Every built-in seed-library tool has an explainer."""
        expected = {
            "cluster_analysis",
            "correlation_analysis",
            "cross_validation",
            "data_profiler",
            "descriptive_stats",
            "feature_scaler",
            "gradient_boosting",
            "group_split",
            "hypothesis_tests",
            "linear_mixed_model",
            "linear_regression",
            "logistic_regression",
            "mann_whitney_u",
            "one_way_anova",
            "outlier_detection",
            "paired_t_test",
            "pca",
            "polynomial_regression",
            "random_forest",
            "random_forest_classifier",
            "regularized_regression",
            "time_series_decomposition",
            "train_val_test_split",
            "visualization",
        }
        assert expected <= set(METHOD_GLOSSARY)

    def test_at_least_fifteen_entries(self) -> None:
        assert len(METHOD_GLOSSARY) >= 15

    def test_entries_are_single_line_nonempty(self) -> None:
        for name, text in METHOD_GLOSSARY.items():
            assert text.strip(), f"empty explainer for {name}"
            assert "\n" not in text, f"multi-line explainer for {name}"


class TestExplainMethod:
    def test_exact_match(self) -> None:
        assert explain_method("random_forest") == METHOD_GLOSSARY["random_forest"]

    def test_case_insensitive(self) -> None:
        assert explain_method("Random_Forest") == METHOD_GLOSSARY["random_forest"]

    def test_separator_tolerant(self) -> None:
        assert explain_method("Random Forest") == METHOD_GLOSSARY["random_forest"]

    def test_classifier_gets_own_entry_not_substring_parent(self) -> None:
        result = explain_method("random_forest_classifier")
        assert result == METHOD_GLOSSARY["random_forest_classifier"]
        assert result != METHOD_GLOSSARY["random_forest"]

    def test_fuzzy_contains_suffix(self) -> None:
        """Agent-flavoured names like 'random_forest_tuned' resolve to
        the closest glossary entry."""
        assert explain_method("random_forest_tuned") == METHOD_GLOSSARY["random_forest"]

    def test_unknown_returns_none(self) -> None:
        assert explain_method("quantum_annealing_net") is None

    def test_empty_returns_none(self) -> None:
        assert explain_method("") is None
