"""Tests for orchestrator output parsing."""

from __future__ import annotations

from urika.orchestrator.parsing import (
    parse_evaluation,
    parse_run_records,
    parse_suggestions,
)


class TestParseRunRecords:
    def test_single_run(self) -> None:
        text = """Here are the results:
```json
{
    "run_id": "run-001",
    "method": "linear_regression",
    "params": {"alpha": 0.1},
    "metrics": {"rmse": 0.42, "r2": 0.87}
}
```
"""
        records = parse_run_records(text)
        assert len(records) == 1
        assert records[0].run_id == "run-001"
        assert records[0].method == "linear_regression"
        assert records[0].metrics == {"rmse": 0.42, "r2": 0.87}
        assert records[0].params == {"alpha": 0.1}

    def test_multiple_runs(self) -> None:
        text = """First run:
```json
{
    "run_id": "run-001",
    "method": "linear_regression",
    "params": {},
    "metrics": {"rmse": 0.5}
}
```

Second run:
```json
{
    "run_id": "run-002",
    "method": "ridge_regression",
    "params": {"alpha": 1.0},
    "metrics": {"rmse": 0.3}
}
```
"""
        records = parse_run_records(text)
        assert len(records) == 2
        assert records[0].run_id == "run-001"
        assert records[1].run_id == "run-002"

    def test_ignores_non_run_json(self) -> None:
        text = """Some config:
```json
{
    "model": "gpt-4",
    "temperature": 0.7
}
```
"""
        records = parse_run_records(text)
        assert len(records) == 0

    def test_empty_text(self) -> None:
        records = parse_run_records("")
        assert len(records) == 0

    def test_no_json_blocks(self) -> None:
        text = "Just some plain text without any code blocks."
        records = parse_run_records(text)
        assert len(records) == 0

    def test_malformed_json_skipped(self) -> None:
        text = """Bad block:
```json
{not valid json}
```

Good block:
```json
{
    "run_id": "run-001",
    "method": "ols",
    "params": {},
    "metrics": {"r2": 0.9}
}
```
"""
        records = parse_run_records(text)
        assert len(records) == 1
        assert records[0].run_id == "run-001"


class TestParseEvaluation:
    def test_extracts_evaluation(self) -> None:
        text = """Evaluation complete:
```json
{
    "criteria_met": true,
    "score": 0.95,
    "reasoning": "All criteria satisfied"
}
```
"""
        result = parse_evaluation(text)
        assert result is not None
        assert result["criteria_met"] is True
        assert result["score"] == 0.95

    def test_returns_none_when_no_evaluation(self) -> None:
        text = "No evaluation here, just text."
        result = parse_evaluation(text)
        assert result is None

    def test_returns_none_for_non_evaluation_json(self) -> None:
        text = """Some other JSON:
```json
{
    "run_id": "run-001",
    "method": "linear",
    "metrics": {"r2": 0.5}
}
```
"""
        result = parse_evaluation(text)
        assert result is None


class TestParseSuggestions:
    def test_extracts_suggestions(self) -> None:
        text = """Here are my suggestions:
```json
{
    "suggestions": [
        {"method": "random_forest", "rationale": "Try non-linear"},
        {"method": "gradient_boosting", "rationale": "Ensemble approach"}
    ],
    "needs_tool": false
}
```
"""
        result = parse_suggestions(text)
        assert result is not None
        assert len(result["suggestions"]) == 2
        assert result["needs_tool"] is False

    def test_returns_none_when_no_suggestions(self) -> None:
        text = """Nothing relevant:
```json
{
    "criteria_met": false
}
```
"""
        result = parse_suggestions(text)
        assert result is None

    def test_detects_needs_tool(self) -> None:
        text = """Need a custom tool:
```json
{
    "suggestions": [
        {"method": "custom_analysis", "rationale": "Needs preprocessing"}
    ],
    "needs_tool": true,
    "tool_description": "Data preprocessor for time series"
}
```
"""
        result = parse_suggestions(text)
        assert result is not None
        assert result["needs_tool"] is True
        assert "tool_description" in result
