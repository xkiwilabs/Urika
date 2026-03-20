"""Tests for method registry."""

from __future__ import annotations

from pathlib import Path

from urika.core.method_registry import (
    register_method,
    load_methods,
    get_best_method,
    update_method_status,
)


class TestRegisterMethod:
    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="my_method",
            description="Test",
            script="experiments/exp-001/methods/my.py",
            experiment="exp-001",
            turn=1,
            metrics={"accuracy": 0.8},
        )
        assert (tmp_path / "methods.json").exists()

    def test_appends_method(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="m1",
            description="First",
            script="s1.py",
            experiment="e1",
            turn=1,
            metrics={},
        )
        register_method(
            tmp_path,
            name="m2",
            description="Second",
            script="s2.py",
            experiment="e1",
            turn=2,
            metrics={},
        )
        methods = load_methods(tmp_path)
        assert len(methods) == 2

    def test_updates_existing_method(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="m1",
            description="v1",
            script="s1.py",
            experiment="e1",
            turn=1,
            metrics={"acc": 0.5},
        )
        register_method(
            tmp_path,
            name="m1",
            description="v2",
            script="s1.py",
            experiment="e1",
            turn=2,
            metrics={"acc": 0.7},
        )
        methods = load_methods(tmp_path)
        assert len(methods) == 1
        assert methods[0]["metrics"]["acc"] == 0.7

    def test_default_status_active(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="m1",
            description="",
            script="s.py",
            experiment="e1",
            turn=1,
            metrics={},
        )
        methods = load_methods(tmp_path)
        assert methods[0]["status"] == "active"


class TestLoadMethods:
    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_methods(tmp_path) == []

    def test_returns_all_methods(self, tmp_path: Path) -> None:
        for i in range(3):
            register_method(
                tmp_path,
                name=f"m{i}",
                description=f"Method {i}",
                script=f"s{i}.py",
                experiment="e1",
                turn=i,
                metrics={"acc": i * 0.1},
            )
        assert len(load_methods(tmp_path)) == 3


class TestGetBestMethod:
    def test_returns_best_by_metric(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="low",
            description="",
            script="s.py",
            experiment="e1",
            turn=1,
            metrics={"acc": 0.5},
        )
        register_method(
            tmp_path,
            name="high",
            description="",
            script="s.py",
            experiment="e1",
            turn=2,
            metrics={"acc": 0.9},
        )
        best = get_best_method(tmp_path, metric="acc", direction="higher")
        assert best is not None
        assert best["name"] == "high"

    def test_returns_best_lower_is_better(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="low",
            description="",
            script="s.py",
            experiment="e1",
            turn=1,
            metrics={"rmse": 0.1},
        )
        register_method(
            tmp_path,
            name="high",
            description="",
            script="s.py",
            experiment="e1",
            turn=2,
            metrics={"rmse": 0.9},
        )
        best = get_best_method(tmp_path, metric="rmse", direction="lower")
        assert best is not None
        assert best["name"] == "low"

    def test_returns_none_when_empty(self, tmp_path: Path) -> None:
        assert get_best_method(tmp_path, metric="acc", direction="higher") is None

    def test_skips_methods_without_metric(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="no_acc",
            description="",
            script="s.py",
            experiment="e1",
            turn=1,
            metrics={"rmse": 0.5},
        )
        register_method(
            tmp_path,
            name="has_acc",
            description="",
            script="s.py",
            experiment="e1",
            turn=2,
            metrics={"acc": 0.7},
        )
        best = get_best_method(tmp_path, metric="acc", direction="higher")
        assert best is not None
        assert best["name"] == "has_acc"


class TestUpdateMethodStatus:
    def test_updates_status(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="m1",
            description="",
            script="s.py",
            experiment="e1",
            turn=1,
            metrics={},
        )
        update_method_status(tmp_path, "m1", "superseded", superseded_by="m2")
        methods = load_methods(tmp_path)
        assert methods[0]["status"] == "superseded"
        assert methods[0]["superseded_by"] == "m2"

    def test_update_nonexistent_does_nothing(self, tmp_path: Path) -> None:
        register_method(
            tmp_path,
            name="m1",
            description="",
            script="s.py",
            experiment="e1",
            turn=1,
            metrics={},
        )
        update_method_status(tmp_path, "nonexistent", "failed")
        methods = load_methods(tmp_path)
        assert methods[0]["status"] == "active"
