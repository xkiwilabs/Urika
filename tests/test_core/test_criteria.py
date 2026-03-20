"""Tests for criteria system."""

from __future__ import annotations

import json
from pathlib import Path

from urika.core.criteria import (
    CriteriaVersion,
    append_criteria,
    load_criteria,
    load_criteria_history,
)


class TestCriteriaVersion:
    def test_to_dict(self) -> None:
        v = CriteriaVersion(
            version=1,
            set_by="project_builder",
            turn=0,
            rationale="Initial",
            criteria={"type": "exploratory"},
        )
        d = v.to_dict()
        assert d["version"] == 1
        assert d["set_by"] == "project_builder"

    def test_from_dict(self) -> None:
        d = {
            "version": 1,
            "set_by": "user",
            "turn": 0,
            "rationale": "x",
            "criteria": {},
        }
        v = CriteriaVersion.from_dict(d)
        assert v.version == 1
        assert v.set_by == "user"


class TestLoadCriteria:
    def test_no_file_returns_none(self, tmp_path: Path) -> None:
        assert load_criteria(tmp_path) is None

    def test_returns_latest_version(self, tmp_path: Path) -> None:
        data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "a",
                    "turn": 0,
                    "rationale": "",
                    "criteria": {"type": "exploratory"},
                },
                {
                    "version": 2,
                    "set_by": "b",
                    "turn": 1,
                    "rationale": "",
                    "criteria": {"type": "predictive"},
                },
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(data))
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.version == 2
        assert v.criteria["type"] == "predictive"


class TestLoadCriteriaHistory:
    def test_returns_all_versions(self, tmp_path: Path) -> None:
        data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "a",
                    "turn": 0,
                    "rationale": "",
                    "criteria": {},
                },
                {
                    "version": 2,
                    "set_by": "b",
                    "turn": 1,
                    "rationale": "",
                    "criteria": {},
                },
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(data))
        history = load_criteria_history(tmp_path)
        assert len(history) == 2

    def test_no_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_criteria_history(tmp_path) == []


class TestAppendCriteria:
    def test_creates_file_if_missing(self, tmp_path: Path) -> None:
        append_criteria(
            tmp_path, {"type": "exploratory"}, set_by="user", turn=0, rationale="Init"
        )
        assert (tmp_path / "criteria.json").exists()
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.version == 1

    def test_appends_new_version(self, tmp_path: Path) -> None:
        append_criteria(
            tmp_path,
            {"type": "exploratory"},
            set_by="builder",
            turn=0,
            rationale="First",
        )
        append_criteria(
            tmp_path,
            {
                "type": "predictive",
                "threshold": {"primary": {"metric": "acc", "target": 0.8}},
            },
            set_by="suggestion",
            turn=3,
            rationale="Baselines done",
        )
        history = load_criteria_history(tmp_path)
        assert len(history) == 2
        assert history[-1].version == 2
        assert history[-1].criteria["type"] == "predictive"

    def test_version_auto_increments(self, tmp_path: Path) -> None:
        append_criteria(tmp_path, {}, set_by="a", turn=0, rationale="")
        append_criteria(tmp_path, {}, set_by="b", turn=1, rationale="")
        append_criteria(tmp_path, {}, set_by="c", turn=2, rationale="")
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.version == 3

    def test_primary_threshold_met(self, tmp_path: Path) -> None:
        append_criteria(
            tmp_path,
            {
                "threshold": {
                    "primary": {
                        "metric": "accuracy",
                        "target": 0.8,
                        "direction": "higher",
                    }
                }
            },
            set_by="user",
            turn=0,
            rationale="",
        )
        v = load_criteria(tmp_path)
        assert v is not None
        assert v.criteria["threshold"]["primary"]["target"] == 0.8
