"""Tests for GroupSplitTool."""

from __future__ import annotations

import pandas as pd

from urika.data.models import DatasetSpec, DatasetView
from urika.data.profiler import profile_dataset
from urika.tools.base import ITool
from urika.tools.group_split import GroupSplitTool, get_tool


def _make_view(df: pd.DataFrame) -> DatasetView:
    return DatasetView(
        spec=DatasetSpec(path="test.csv", format="csv"),
        data=df,
        summary=profile_dataset(df),
    )


def _sample_df() -> pd.DataFrame:
    """4 participants, 3 rows each = 12 rows total."""
    return pd.DataFrame(
        {
            "participant": ["A"] * 3 + ["B"] * 3 + ["C"] * 3 + ["D"] * 3,
            "value": list(range(12)),
        }
    )


class TestGroupSplitMetadata:
    def test_name(self) -> None:
        tool = GroupSplitTool()
        assert tool.name() == "group_split"

    def test_description(self) -> None:
        tool = GroupSplitTool()
        assert isinstance(tool.description(), str)
        assert len(tool.description()) > 0

    def test_category(self) -> None:
        tool = GroupSplitTool()
        assert tool.category() == "preprocessing"

    def test_default_params(self) -> None:
        tool = GroupSplitTool()
        params = tool.default_params()
        assert params["group_column"] == ""
        assert params["mode"] == "logo"
        assert params["test_groups"] == 1
        assert params["val_groups"] == 0
        assert params["random_state"] == 42


class TestLogoMode:
    def test_correct_number_of_folds(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "logo"})
        assert result.valid is True
        assert result.outputs["n_groups"] == 4
        assert len(result.outputs["folds"]) == 4

    def test_each_fold_has_one_test_group(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "logo"})
        for fold in result.outputs["folds"]:
            assert len(fold["test_groups"]) == 1

    def test_train_and_test_indices_disjoint(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "logo"})
        for fold in result.outputs["folds"]:
            train_set = set(fold["train_indices"])
            test_set = set(fold["test_indices"])
            assert train_set & test_set == set()

    def test_all_indices_covered_across_folds(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "logo"})
        all_test_indices: set[int] = set()
        for fold in result.outputs["folds"]:
            all_test_indices.update(fold["test_indices"])
        assert all_test_indices == set(range(len(df)))

    def test_logo_metrics(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "logo"})
        assert result.metrics["n_groups"] == 4.0


class TestSplitMode:
    def test_basic_one_group_test(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(
            view,
            {"group_column": "participant", "mode": "split", "test_groups": 1},
        )
        assert result.valid is True
        assert len(result.outputs["test_groups"]) == 1
        assert len(result.outputs["train_groups"]) == 3
        assert result.outputs["val_groups"] == []

    def test_with_validation_groups(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(
            view,
            {
                "group_column": "participant",
                "mode": "split",
                "test_groups": 1,
                "val_groups": 1,
            },
        )
        assert result.valid is True
        assert len(result.outputs["test_groups"]) == 1
        assert len(result.outputs["val_groups"]) == 1
        assert len(result.outputs["train_groups"]) == 2

    def test_groups_stay_intact(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(
            view,
            {"group_column": "participant", "mode": "split", "test_groups": 1},
        )
        # All rows for each test group should be in test_indices
        test_grp = result.outputs["test_groups"][0]
        expected_indices = df.index[df["participant"] == test_grp].tolist()
        assert sorted(result.outputs["test_indices"]) == sorted(expected_indices)

    def test_custom_random_state(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result_a = tool.run(
            view,
            {
                "group_column": "participant",
                "mode": "split",
                "test_groups": 1,
                "random_state": 0,
            },
        )
        result_b = tool.run(
            view,
            {
                "group_column": "participant",
                "mode": "split",
                "test_groups": 1,
                "random_state": 99,
            },
        )
        # Different seeds should (very likely) produce different splits
        # At minimum, both should be valid
        assert result_a.valid is True
        assert result_b.valid is True

    def test_split_metrics(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(
            view,
            {
                "group_column": "participant",
                "mode": "split",
                "test_groups": 1,
                "val_groups": 1,
            },
        )
        assert result.metrics["n_groups"] == 4.0
        total_frac = (
            result.metrics["train_fraction"]
            + result.metrics["val_fraction"]
            + result.metrics["test_fraction"]
        )
        assert abs(total_frac - 1.0) < 1e-9

    def test_split_sizes_sum_to_total(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(
            view,
            {
                "group_column": "participant",
                "mode": "split",
                "test_groups": 1,
                "val_groups": 1,
            },
        )
        total = (
            result.outputs["train_size"]
            + result.outputs["val_size"]
            + result.outputs["test_size"]
        )
        assert total == len(df)


class TestGroupSplitErrors:
    def test_group_column_not_specified(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"mode": "logo"})
        assert result.valid is False
        assert "group_column" in result.error

    def test_group_column_not_found(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "nonexistent", "mode": "logo"})
        assert result.valid is False
        assert "nonexistent" in result.error

    def test_fewer_than_two_groups(self) -> None:
        df = pd.DataFrame({"participant": ["A"] * 5, "value": list(range(5))})
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "logo"})
        assert result.valid is False
        assert "2 groups" in result.error

    def test_test_plus_val_groups_too_many(self) -> None:
        df = _sample_df()  # 4 groups
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(
            view,
            {
                "group_column": "participant",
                "mode": "split",
                "test_groups": 2,
                "val_groups": 2,
            },
        )
        assert result.valid is False
        assert "must be <" in result.error

    def test_unknown_mode(self) -> None:
        df = _sample_df()
        view = _make_view(df)
        tool = GroupSplitTool()
        result = tool.run(view, {"group_column": "participant", "mode": "bad"})
        assert result.valid is False
        assert "Unknown mode" in result.error


class TestGroupSplitFactory:
    def test_get_tool_returns_itool(self) -> None:
        tool = get_tool()
        assert isinstance(tool, ITool)
        assert isinstance(tool, GroupSplitTool)
