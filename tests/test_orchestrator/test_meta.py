"""Tests for the meta-orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from urika.orchestrator.meta import _criteria_fully_met


class TestCriteriaFullyMet:
    def test_returns_false_when_no_criteria_file(self, tmp_path: Path) -> None:
        """No criteria.json means exploratory — never done."""
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_when_empty_versions(self, tmp_path: Path) -> None:
        """Empty versions list means no criteria set."""
        (tmp_path / "criteria.json").write_text(json.dumps({"versions": []}))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_when_no_threshold(self, tmp_path: Path) -> None:
        """Criteria without threshold = exploratory, never auto-done."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Initial criteria",
                    "criteria": {"type": "exploratory"},
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_when_no_primary_threshold(self, tmp_path: Path) -> None:
        """Threshold without primary metric means not fully specified."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Partial criteria",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {"secondary": {}},
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))
        assert _criteria_fully_met(tmp_path) is False

    def test_returns_false_even_with_primary_threshold(self, tmp_path: Path) -> None:
        """Current implementation always returns False — advisor decides."""
        criteria_data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "advisor_agent",
                    "turn": 1,
                    "rationale": "Target set",
                    "criteria": {
                        "type": "threshold",
                        "threshold": {
                            "primary": {
                                "metric": "accuracy",
                                "direction": ">",
                                "target": 0.9,
                            }
                        },
                    },
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(criteria_data))
        assert _criteria_fully_met(tmp_path) is False
