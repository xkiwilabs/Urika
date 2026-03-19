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
            name="test", question="Q?", mode="exploratory",
            description="Predict target choices in herding task"
        )
        assert config.description == "Predict target choices in herding task"

    def test_description_default_empty(self) -> None:
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        assert config.description == ""

    def test_description_roundtrips_via_toml(self) -> None:
        config = ProjectConfig(
            name="test", question="Q?", mode="exploratory",
            description="My project description"
        )
        d = config.to_toml_dict()
        restored = ProjectConfig.from_toml_dict(d)
        assert restored.description == "My project description"


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
