"""Tests for notification query functions."""

from __future__ import annotations

import json

from urika.notifications.queries import (
    get_criteria_text,
    get_experiments_text,
    get_logs_text,
    get_methods_text,
    get_results_text,
    get_status_text,
    get_usage_text,
)


class TestQueries:
    def test_status_no_project(self, tmp_path):
        assert "not found" in get_status_text(tmp_path).lower()

    def test_results_no_leaderboard(self, tmp_path):
        assert "no results" in get_results_text(tmp_path).lower()

    def test_methods_no_file(self, tmp_path):
        assert "no methods" in get_methods_text(tmp_path).lower()

    def test_criteria_no_file(self, tmp_path):
        assert "no criteria" in get_criteria_text(tmp_path).lower()

    def test_experiments_no_dir(self, tmp_path):
        text = get_experiments_text(tmp_path)
        assert "0" in text or "no experiment" in text.lower()

    def test_usage_no_file(self, tmp_path):
        text = get_usage_text(tmp_path)
        assert "no usage" in text.lower() or "0" in text

    def test_logs_no_data(self, tmp_path):
        text = get_logs_text(tmp_path)
        assert "no log" in text.lower() or "no experiment" in text.lower()

    # ── Tests with data present ──

    def test_methods_with_data(self, tmp_path):
        data = {
            "methods": [
                {
                    "name": "linear_reg",
                    "status": "active",
                    "metrics": {"r2": 0.85, "rmse": 1.2},
                },
                {
                    "name": "random_forest",
                    "status": "superseded",
                    "metrics": {"r2": 0.78},
                },
            ]
        }
        (tmp_path / "methods.json").write_text(json.dumps(data), encoding="utf-8")
        text = get_methods_text(tmp_path)
        assert "Methods (2):" in text
        assert "linear_reg [active]" in text
        assert "r2=0.85" in text
        assert "random_forest [superseded]" in text

    def test_criteria_with_data(self, tmp_path):
        data = {
            "versions": [
                {
                    "version": 1,
                    "set_by": "user",
                    "turn": 0,
                    "rationale": "initial criteria",
                    "criteria": {"primary_metric": "r2", "threshold": 0.8},
                }
            ]
        }
        (tmp_path / "criteria.json").write_text(json.dumps(data), encoding="utf-8")
        text = get_criteria_text(tmp_path)
        assert "Criteria (v1" in text
        assert "primary_metric" in text
        assert "r2" in text

    def test_experiments_with_data(self, tmp_path):
        exp_dir = tmp_path / "experiments" / "exp-001-baseline"
        exp_dir.mkdir(parents=True)
        exp_config = {
            "experiment_id": "exp-001-baseline",
            "name": "Baseline models",
            "hypothesis": "Linear works",
            "builds_on": [],
        }
        (exp_dir / "experiment.json").write_text(
            json.dumps(exp_config), encoding="utf-8"
        )
        progress = {
            "experiment_id": "exp-001-baseline",
            "status": "running",
            "runs": [{"method": "lr", "metrics": {}}],
        }
        (exp_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
        text = get_experiments_text(tmp_path)
        assert "Experiments (1):" in text
        assert "exp-001-baseline" in text
        assert "Baseline models" in text
        assert "running" in text
        assert "1 runs" in text

    def test_usage_with_data(self, tmp_path):
        data = {
            "sessions": [{"duration_ms": 1000}],
            "totals": {
                "sessions": 3,
                "total_duration_ms": 60000,
                "total_tokens_in": 5000,
                "total_tokens_out": 2000,
                "total_cost_usd": 1.23,
                "total_agent_calls": 15,
                "total_experiments": 4,
            },
        }
        (tmp_path / "usage.json").write_text(json.dumps(data), encoding="utf-8")
        text = get_usage_text(tmp_path)
        assert "Usage:" in text
        assert "Sessions: 3" in text
        assert "Tokens: 7000" in text
        assert "$1.23" in text
        assert "Agent calls: 15" in text

    def test_logs_with_data(self, tmp_path):
        exp_dir = tmp_path / "experiments" / "exp-001-test"
        exp_dir.mkdir(parents=True)
        exp_config = {
            "experiment_id": "exp-001-test",
            "name": "Test experiment",
            "hypothesis": "test",
            "builds_on": [],
        }
        (exp_dir / "experiment.json").write_text(
            json.dumps(exp_config), encoding="utf-8"
        )
        runs = [
            {
                "method": f"method_{i}",
                "metrics": {"r2": 0.5 + i * 0.1},
                "observation": f"Run {i} observation text",
            }
            for i in range(7)
        ]
        progress = {
            "experiment_id": "exp-001-test",
            "status": "completed",
            "runs": runs,
        }
        (exp_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
        text = get_logs_text(tmp_path)
        assert "Logs for exp-001-test" in text
        assert "last 5 of 7" in text
        # Should show runs 2-6 (last 5), not 0-1
        assert "method_2" in text
        assert "method_6" in text
        assert "method_0" not in text

    def test_logs_truncates_observations(self, tmp_path):
        exp_dir = tmp_path / "experiments" / "exp-001-long"
        exp_dir.mkdir(parents=True)
        exp_config = {
            "experiment_id": "exp-001-long",
            "name": "Long obs",
            "hypothesis": "test",
            "builds_on": [],
        }
        (exp_dir / "experiment.json").write_text(
            json.dumps(exp_config), encoding="utf-8"
        )
        long_obs = "A" * 300
        progress = {
            "experiment_id": "exp-001-long",
            "status": "completed",
            "runs": [{"method": "m1", "metrics": {}, "observation": long_obs}],
        }
        (exp_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
        text = get_logs_text(tmp_path, experiment_id="exp-001-long")
        assert "..." in text
        # Should not contain the full 300-char string
        assert long_obs not in text

    def test_logs_specific_experiment(self, tmp_path):
        for eid in ["exp-001-first", "exp-002-second"]:
            exp_dir = tmp_path / "experiments" / eid
            exp_dir.mkdir(parents=True)
            (exp_dir / "experiment.json").write_text(
                json.dumps(
                    {
                        "experiment_id": eid,
                        "name": eid,
                        "hypothesis": "h",
                        "builds_on": [],
                    }
                ),
                encoding="utf-8",
            )
            (exp_dir / "progress.json").write_text(
                json.dumps(
                    {
                        "experiment_id": eid,
                        "status": "completed",
                        "runs": [
                            {"method": f"m-{eid}", "metrics": {}, "observation": "ok"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
        text = get_logs_text(tmp_path, experiment_id="exp-001-first")
        assert "exp-001-first" in text
        assert "m-exp-001-first" in text
