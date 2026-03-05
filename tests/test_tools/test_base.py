"""Tests for ITool ABC and ToolResult."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from urika.data.models import DatasetSpec, DataSummary, DatasetView
from urika.tools.base import ITool, ToolResult


class DummyTool(ITool):
    """Concrete tool for testing."""

    def name(self) -> str:
        return "dummy_tool"

    def description(self) -> str:
        return "A dummy tool for testing"

    def category(self) -> str:
        return "exploration"

    def default_params(self) -> dict[str, Any]:
        return {"top_n": 10}

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        return ToolResult(
            outputs={"column_count": 3, "summary": "all good"},
            artifacts=["profile.html"],
        )


class TestToolResult:
    def test_create_with_required_fields(self) -> None:
        result = ToolResult(outputs={"count": 42})
        assert result.outputs == {"count": 42}
        assert result.artifacts == []
        assert result.valid is True
        assert result.error is None

    def test_create_with_failure(self) -> None:
        result = ToolResult(
            outputs={},
            valid=False,
            error="Missing required column",
        )
        assert result.valid is False
        assert result.error == "Missing required column"

    def test_create_with_artifacts(self) -> None:
        result = ToolResult(
            outputs={"stats": {"mean": 1.5}},
            artifacts=["plot.png", "report.csv"],
        )
        assert len(result.artifacts) == 2


class TestITool:
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ITool()  # type: ignore[abstract]

    def test_concrete_implementation_metadata(self) -> None:
        tool = DummyTool()
        assert tool.name() == "dummy_tool"
        assert tool.description() == "A dummy tool for testing"
        assert tool.category() == "exploration"

    def test_default_params(self) -> None:
        tool = DummyTool()
        params = tool.default_params()
        assert params == {"top_n": 10}

    def test_run_returns_tool_result(self) -> None:
        tool = DummyTool()
        data = DatasetView(
            spec=DatasetSpec(path=Path("/tmp/test.csv"), format="csv"),
            data=pd.DataFrame({"x": [1, 2, 3]}),
            summary=DataSummary(
                n_rows=3,
                n_columns=1,
                columns=["x"],
                dtypes={"x": "int64"},
                missing_counts={"x": 0},
                numeric_stats={
                    "x": {
                        "mean": 2.0,
                        "std": 1.0,
                        "min": 1.0,
                        "max": 3.0,
                        "median": 2.0,
                    }
                },
            ),
        )
        result = tool.run(data, {"top_n": 10})
        assert isinstance(result, ToolResult)
        assert result.outputs["column_count"] == 3
        assert result.valid is True
