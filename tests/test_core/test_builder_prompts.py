"""Tests for builder prompt functions."""

from __future__ import annotations

from pathlib import Path

from urika.core.builder_prompts import (
    build_planning_prompt,
    build_scoping_prompt,
    build_suggestion_prompt,
)
from urika.core.source_scanner import ScanResult
from urika.data.models import DataSummary


def _make_summary() -> DataSummary:
    return DataSummary(
        n_rows=100,
        n_columns=5,
        columns=["x", "y", "z", "group", "target"],
        dtypes={
            "x": "float64",
            "y": "float64",
            "z": "float64",
            "group": "object",
            "target": "int64",
        },
        missing_counts={"x": 0, "y": 2, "z": 0, "group": 0, "target": 0},
        numeric_stats={},
    )


def _make_scan() -> ScanResult:
    return ScanResult(
        root=Path("/tmp/test"),
        data_files=[Path("/tmp/test/data.csv")],
        data_directories=[Path("/tmp/test")],
    )


class TestBuildScopingPrompt:
    def test_includes_description(self) -> None:
        prompt = build_scoping_prompt(_make_scan(), None, "Predict targets")
        assert "Predict targets" in prompt

    def test_includes_scan_summary(self) -> None:
        prompt = build_scoping_prompt(_make_scan(), None, "desc")
        assert "Data files" in prompt

    def test_includes_data_profile(self) -> None:
        prompt = build_scoping_prompt(_make_scan(), _make_summary(), "desc")
        assert "Rows: 100" in prompt
        assert "Columns: 5" in prompt

    def test_includes_context(self) -> None:
        prompt = build_scoping_prompt(
            _make_scan(), None, "desc", context="Prior answer"
        )
        assert "Prior answer" in prompt

    def test_no_description(self) -> None:
        prompt = build_scoping_prompt(_make_scan(), None, "")
        assert "No description provided" in prompt


class TestBuildSuggestionPrompt:
    def test_includes_description(self) -> None:
        prompt = build_suggestion_prompt("Predict X", None, {})
        assert "Predict X" in prompt

    def test_includes_answers(self) -> None:
        prompt = build_suggestion_prompt("desc", None, {"What?": "This"})
        assert "What?" in prompt
        assert "This" in prompt

    def test_includes_data_summary(self) -> None:
        prompt = build_suggestion_prompt("desc", _make_summary(), {})
        assert "100" in prompt


class TestBuildPlanningPrompt:
    def test_includes_suggestions(self) -> None:
        prompt = build_planning_prompt(
            {"suggestions": [{"name": "baseline"}]}, "desc", None
        )
        assert "baseline" in prompt

    def test_includes_description(self) -> None:
        prompt = build_planning_prompt({}, "My research", None)
        assert "My research" in prompt
