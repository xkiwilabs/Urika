"""Tests for core data models."""

import json

import pytest

from urika.core.models import (
    ExperimentConfig,
    ProjectConfig,
    RunRecord,
)


class TestProjectConfig:
    def test_create_minimal(self) -> None:
        config = ProjectConfig(
            name="sleep-quality",
            question="What predicts sleep quality?",
            mode="exploratory",
        )
        assert config.name == "sleep-quality"
        assert config.question == "What predicts sleep quality?"
        assert config.mode == "exploratory"

    def test_create_with_all_fields(self) -> None:
        config = ProjectConfig(
            name="sleep-quality",
            question="What predicts sleep quality?",
            mode="exploratory",
            data_paths=["data/sleep_survey.csv"],
            success_criteria={"r2": {"min": 0.3}},
        )
        assert config.data_paths == ["data/sleep_survey.csv"]
        assert config.success_criteria == {"r2": {"min": 0.3}}

    def test_mode_validation(self) -> None:
        """Only exploratory, confirmatory, pipeline are valid modes."""
        with pytest.raises(ValueError, match="mode"):
            ProjectConfig(
                name="test",
                question="test?",
                mode="invalid",
            )

    def test_to_toml_dict(self) -> None:
        config = ProjectConfig(
            name="sleep-quality",
            question="What predicts sleep quality?",
            mode="exploratory",
        )
        d = config.to_toml_dict()
        assert d["project"]["name"] == "sleep-quality"
        assert d["project"]["question"] == "What predicts sleep quality?"
        assert d["project"]["mode"] == "exploratory"

    def test_from_toml_dict(self) -> None:
        d = {
            "project": {
                "name": "sleep-quality",
                "question": "What predicts sleep quality?",
                "mode": "exploratory",
            }
        }
        config = ProjectConfig.from_toml_dict(d)
        assert config.name == "sleep-quality"

    def test_roundtrip(self) -> None:
        original = ProjectConfig(
            name="test",
            question="Does X cause Y?",
            mode="confirmatory",
            data_paths=["data/survey.csv"],
            success_criteria={"p_value": {"max": 0.05}},
        )
        d = original.to_toml_dict()
        restored = ProjectConfig.from_toml_dict(d)
        assert restored.name == original.name
        assert restored.question == original.question
        assert restored.mode == original.mode
        assert restored.data_paths == original.data_paths
        assert restored.success_criteria == original.success_criteria

    def test_config_with_description(self) -> None:
        config = ProjectConfig(
            name="test",
            question="Q?",
            mode="exploratory",
            description="Predict target choices in herding task",
        )
        assert config.description == "Predict target choices in herding task"

    def test_description_default_empty(self) -> None:
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        assert config.description == ""

    def test_description_roundtrips_via_toml(self) -> None:
        config = ProjectConfig(
            name="test",
            question="Q?",
            mode="exploratory",
            description="My project description",
        )
        d = config.to_toml_dict()
        restored = ProjectConfig.from_toml_dict(d)
        assert restored.description == "My project description"

    def test_audience_default_standard(self) -> None:
        """New projects default to 'standard' — senior undergrad / early
        Masters or PhD reader. Reports and slides explain methods in
        depth (assumes the reader has heard of common methods but
        doesn't know their specifics) without the extra novice
        explainer slides."""
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        assert config.audience == "standard"

    def test_audience_from_toml(self) -> None:
        d = {
            "project": {
                "name": "test",
                "question": "Q?",
                "mode": "exploratory",
            },
            "preferences": {"audience": "novice"},
        }
        config = ProjectConfig.from_toml_dict(d)
        assert config.audience == "novice"

    def test_audience_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="audience"):
            ProjectConfig(
                name="test",
                question="Q?",
                mode="exploratory",
                audience="beginner",
            )

    def test_audience_roundtrips_via_toml(self) -> None:
        config = ProjectConfig(
            name="test",
            question="Q?",
            mode="exploratory",
            audience="novice",
        )
        d = config.to_toml_dict()
        restored = ProjectConfig.from_toml_dict(d)
        assert restored.audience == "novice"

    def test_audience_expert_in_toml(self) -> None:
        """Expert audience should be written to preferences section."""
        config = ProjectConfig(
            name="test", question="Q?", mode="exploratory", audience="expert"
        )
        d = config.to_toml_dict()
        assert d["preferences"]["audience"] == "expert"

    def test_research_intent_roundtrips_via_toml(self) -> None:
        """All four research-intent fields survive a to/from TOML round-trip."""
        config = ProjectConfig(
            name="test",
            question="Q?",
            mode="confirmatory",
            hypotheses=["H1: A predicts B", "H2: effect is stronger in group X"],
            analysis_approach="statistical",
            interpretability_level="interpretable",
            constraints={"interpretability": "results must be explainable in a paper"},
        )
        d = config.to_toml_dict()
        restored = ProjectConfig.from_toml_dict(d)
        assert restored.hypotheses == config.hypotheses
        assert restored.analysis_approach == "statistical"
        assert restored.interpretability_level == "interpretable"
        assert restored.constraints == config.constraints

    def test_research_intent_in_project_block(self) -> None:
        config = ProjectConfig(
            name="test",
            question="Q?",
            mode="exploratory",
            hypotheses=["H1: x"],
            analysis_approach="mixed",
            interpretability_level="balanced",
            constraints={"time": "one week"},
        )
        d = config.to_toml_dict()
        assert d["project"]["hypotheses"] == ["H1: x"]
        assert d["project"]["analysis_approach"] == "mixed"
        assert d["project"]["interpretability_level"] == "balanced"
        assert d["project"]["constraints"] == {"time": "one week"}

    def test_research_intent_omitted_when_empty(self) -> None:
        """Empty research-intent fields don't pollute urika.toml — matches
        the omit-when-empty style of data_paths / success_criteria."""
        d = ProjectConfig(name="test", question="Q?", mode="exploratory").to_toml_dict()
        assert "hypotheses" not in d["project"]
        assert "analysis_approach" not in d["project"]
        assert "interpretability_level" not in d["project"]
        assert "constraints" not in d["project"]

    def test_research_intent_defaults_on_legacy_toml(self) -> None:
        """Pre-v0.8 urika.toml files without research-intent keys load
        with empty defaults rather than raising."""
        d = {
            "project": {
                "name": "legacy",
                "question": "Q?",
                "mode": "exploratory",
            }
        }
        config = ProjectConfig.from_toml_dict(d)
        assert config.hypotheses == []
        assert config.analysis_approach == ""
        assert config.interpretability_level == ""
        assert config.constraints == {}


class TestExperimentConfig:
    def test_create(self) -> None:
        config = ExperimentConfig(
            experiment_id="exp-001-baseline",
            name="Baseline linear models",
            hypothesis="Linear models can establish a reasonable baseline",
        )
        assert config.experiment_id == "exp-001-baseline"
        assert config.name == "Baseline linear models"
        assert config.status == "pending"

    def test_json_roundtrip(self) -> None:
        config = ExperimentConfig(
            experiment_id="exp-001-baseline",
            name="Baseline linear models",
            hypothesis="Linear models establish floor",
            builds_on=["exp-000"],
        )
        data = json.loads(config.to_json())
        restored = ExperimentConfig.from_dict(data)
        assert restored.experiment_id == config.experiment_id
        assert restored.builds_on == ["exp-000"]


class TestRunRecord:
    def test_create(self) -> None:
        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"rmse": 0.15, "r2": 0.72},
            hypothesis="Baseline linear model",
            observation="Nonlinearity in residuals",
            next_step="Try tree-based methods",
        )
        assert run.run_id == "run-001"
        assert run.metrics["r2"] == 0.72
        assert run.timestamp is not None

    def test_to_dict(self) -> None:
        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={},
            metrics={"r2": 0.5},
        )
        d = run.to_dict()
        assert d["run_id"] == "run-001"
        assert "timestamp" in d

    def test_from_dict(self) -> None:
        d = {
            "run_id": "run-001",
            "method": "linear_regression",
            "params": {},
            "metrics": {"r2": 0.5},
            "timestamp": "2026-03-05T10:00:00+00:00",
        }
        run = RunRecord.from_dict(d)
        assert run.run_id == "run-001"
        assert run.metrics == {"r2": 0.5}

    def test_metric_interpretation_default_empty(self) -> None:
        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={},
            metrics={"r2": 0.5},
        )
        assert run.metric_interpretation == {}

    def test_metric_interpretation_roundtrips(self) -> None:
        interp = {
            "r2": (
                "Explains 74% of variance in the target; the criterion "
                "is ≥0.70, so this run meets it."
            )
        }
        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={},
            metrics={"r2": 0.74},
            metric_interpretation=interp,
        )
        d = run.to_dict()
        assert d["metric_interpretation"] == interp
        restored = RunRecord.from_dict(d)
        assert restored.metric_interpretation == interp

    def test_legacy_dict_without_metric_interpretation_loads(self) -> None:
        """Pre-v0.8 run records (no metric_interpretation key) load fine."""
        d = {
            "run_id": "run-001",
            "method": "linear_regression",
            "params": {},
            "metrics": {"r2": 0.5},
            "timestamp": "2026-03-05T10:00:00+00:00",
        }
        run = RunRecord.from_dict(d)
        assert run.metric_interpretation == {}
