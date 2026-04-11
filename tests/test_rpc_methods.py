"""Tests for RPC method registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.rpc.methods import build_registry


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a project workspace for testing."""
    d = tmp_path / "test-project"
    config = ProjectConfig(
        name="test", question="Does X predict Y?", mode="exploratory"
    )
    create_project_workspace(d, config)
    return d


EXPECTED_METHODS = [
    "project.list",
    "project.load_config",
    "experiment.create",
    "experiment.list",
    "experiment.load",
    "progress.append_run",
    "progress.load",
    "progress.get_best_run",
    "session.start",
    "session.pause",
    "session.resume",
    "criteria.load",
    "criteria.append",
    "methods.register",
    "methods.list",
    "usage.record",
    "tools.list",
    "tools.run",
    "code.execute",
    "data.profile",
    "knowledge.ingest",
    "knowledge.search",
    "knowledge.list",
    "labbook.update_notes",
    "labbook.generate_summary",
    "report.results_summary",
    "report.key_findings",
]


class TestRegistryHasExpectedMethods:
    def test_registry_has_expected_methods(self) -> None:
        """All 27 method names exist in the registry."""
        registry = build_registry()
        for method_name in EXPECTED_METHODS:
            assert method_name in registry, f"Missing method: {method_name}"

    def test_registry_count(self) -> None:
        """Registry has exactly 34 methods."""
        registry = build_registry()
        assert len(registry) == 35

    def test_all_handlers_are_callable(self) -> None:
        """Every handler is callable."""
        registry = build_registry()
        for name, handler in registry.items():
            assert callable(handler), f"{name} handler is not callable"


class TestExperimentCreateViaRPC:
    def test_create_experiment(self, project_dir: Path) -> None:
        """Create an experiment through the RPC registry."""
        registry = build_registry()
        result = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Baseline linear models",
                "hypothesis": "Linear models establish a reasonable baseline",
            }
        )
        assert isinstance(result, dict)
        assert result["name"] == "Baseline linear models"
        assert result["hypothesis"] == "Linear models establish a reasonable baseline"
        assert result["status"] == "pending"
        assert result["experiment_id"].startswith("exp-001")

    def test_create_with_builds_on(self, project_dir: Path) -> None:
        """Create an experiment that builds on a previous one."""
        registry = build_registry()
        first = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "First",
                "hypothesis": "Test",
            }
        )
        second = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Second",
                "hypothesis": "Builds on first",
                "builds_on": [first["experiment_id"]],
            }
        )
        assert second["builds_on"] == [first["experiment_id"]]


class TestExperimentListViaRPC:
    def test_list_empty(self, project_dir: Path) -> None:
        """Listing experiments on a fresh project returns empty list."""
        registry = build_registry()
        result = registry["experiment.list"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert result == []

    def test_list_after_create(self, project_dir: Path) -> None:
        """Listing after creating experiments returns them all."""
        registry = build_registry()
        registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "A",
                "hypothesis": "Test A",
            }
        )
        registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "B",
                "hypothesis": "Test B",
            }
        )
        result = registry["experiment.list"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert len(result) == 2
        assert result[0]["name"] == "A"
        assert result[1]["name"] == "B"


class TestExperimentLoadViaRPC:
    def test_load_experiment(self, project_dir: Path) -> None:
        """Load a specific experiment by ID."""
        registry = build_registry()
        created = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Load test",
                "hypothesis": "Can be loaded",
            }
        )
        loaded = registry["experiment.load"](
            {
                "project_dir": str(project_dir),
                "experiment_id": created["experiment_id"],
            }
        )
        assert loaded["name"] == "Load test"
        assert loaded["experiment_id"] == created["experiment_id"]


class TestProjectListViaRPC:
    def test_project_list_returns_list(self) -> None:
        """project.list returns a list (may be empty if no projects registered)."""
        registry = build_registry()
        result = registry["project.list"]({})
        assert isinstance(result, list)

    def test_project_list_entries_have_name_and_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registered projects appear in the list with name and path."""
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / ".urika"))
        from urika.core.registry import ProjectRegistry

        reg = ProjectRegistry()
        reg.register("my-project", tmp_path / "my-project")

        registry = build_registry()
        result = registry["project.list"]({})
        assert len(result) >= 1
        entry = next(e for e in result if e["name"] == "my-project")
        assert entry["path"] == str(tmp_path / "my-project")


class TestProjectLoadConfigViaRPC:
    def test_load_config(self, project_dir: Path) -> None:
        """Load project config via RPC."""
        registry = build_registry()
        result = registry["project.load_config"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["question"] == "Does X predict Y?"
        assert result["mode"] == "exploratory"


class TestProgressViaRPC:
    def test_append_and_load(self, project_dir: Path) -> None:
        """Append a run then load progress."""
        registry = build_registry()
        exp = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Progress test",
                "hypothesis": "Track progress",
            }
        )
        eid = exp["experiment_id"]

        registry["progress.append_run"](
            {
                "project_dir": str(project_dir),
                "experiment_id": eid,
                "run": {
                    "run_id": "run-001",
                    "method": "linear_regression",
                    "params": {"alpha": 0.1},
                    "metrics": {"r2": 0.85},
                },
            }
        )

        progress = registry["progress.load"](
            {
                "project_dir": str(project_dir),
                "experiment_id": eid,
            }
        )
        assert len(progress["runs"]) == 1
        assert progress["runs"][0]["method"] == "linear_regression"

    def test_get_best_run(self, project_dir: Path) -> None:
        """Get the best run by metric."""
        registry = build_registry()
        exp = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Best run test",
                "hypothesis": "Find best",
            }
        )
        eid = exp["experiment_id"]

        for i, r2 in enumerate([0.7, 0.9, 0.8]):
            registry["progress.append_run"](
                {
                    "project_dir": str(project_dir),
                    "experiment_id": eid,
                    "run": {
                        "run_id": f"run-{i:03d}",
                        "method": f"method_{i}",
                        "params": {},
                        "metrics": {"r2": r2},
                    },
                }
            )

        best = registry["progress.get_best_run"](
            {
                "project_dir": str(project_dir),
                "experiment_id": eid,
                "metric": "r2",
                "direction": "higher",
            }
        )
        assert best is not None
        assert best["run_id"] == "run-001"
        assert best["metrics"]["r2"] == 0.9


class TestCriteriaViaRPC:
    def test_load_empty(self, project_dir: Path) -> None:
        """Load criteria on a fresh project returns None."""
        registry = build_registry()
        result = registry["criteria.load"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert result is None

    def test_append_and_load(self, project_dir: Path) -> None:
        """Append criteria then load the latest."""
        registry = build_registry()
        registry["criteria.append"](
            {
                "project_dir": str(project_dir),
                "criteria": {"type": "threshold", "primary": {"r2": 0.8}},
                "set_by": "user",
                "turn": 0,
                "rationale": "Initial criteria",
            }
        )

        result = registry["criteria.load"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert result is not None
        assert result["version"] == 1
        assert result["criteria"]["type"] == "threshold"


class TestMethodsViaRPC:
    def test_list_empty(self, project_dir: Path) -> None:
        """List methods on a fresh project returns empty."""
        registry = build_registry()
        result = registry["methods.list"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert result == []

    def test_register_and_list(self, project_dir: Path) -> None:
        """Register a method then list it."""
        registry = build_registry()
        registry["methods.register"](
            {
                "project_dir": str(project_dir),
                "name": "linear_reg_v1",
                "description": "Basic linear regression",
                "script": "methods/linear_reg_v1.py",
                "experiment": "exp-001",
                "turn": 1,
                "metrics": {"r2": 0.85},
            }
        )

        result = registry["methods.list"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert len(result) == 1
        assert result[0]["name"] == "linear_reg_v1"


class TestLabbookViaRPC:
    def test_update_notes(self, project_dir: Path) -> None:
        """Update experiment notes without error."""
        registry = build_registry()
        exp = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Labbook test",
                "hypothesis": "Notes get generated",
            }
        )
        # Should not raise
        result = registry["labbook.update_notes"](
            {
                "project_dir": str(project_dir),
                "experiment_id": exp["experiment_id"],
            }
        )
        assert result is None

    def test_generate_summary(self, project_dir: Path) -> None:
        """Generate experiment summary without error."""
        registry = build_registry()
        exp = registry["experiment.create"](
            {
                "project_dir": str(project_dir),
                "name": "Summary test",
                "hypothesis": "Summary gets generated",
            }
        )
        result = registry["labbook.generate_summary"](
            {
                "project_dir": str(project_dir),
                "experiment_id": exp["experiment_id"],
            }
        )
        assert result is None


class TestReportViaRPC:
    def test_results_summary(self, project_dir: Path) -> None:
        """Generate results summary without error."""
        registry = build_registry()
        result = registry["report.results_summary"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert result is None

    def test_key_findings(self, project_dir: Path) -> None:
        """Generate key findings without error."""
        registry = build_registry()
        result = registry["report.key_findings"](
            {
                "project_dir": str(project_dir),
            }
        )
        assert result is None


class TestCodeExecuteViaRPC:
    def test_execute_simple(self) -> None:
        """Execute a simple Python expression."""
        registry = build_registry()
        result = registry["code.execute"](
            {
                "code": "print(2 + 2)",
            }
        )
        assert result["exit_code"] == 0
        assert "4" in result["stdout"]

    def test_execute_error(self) -> None:
        """Execution with an error returns non-zero exit code."""
        registry = build_registry()
        result = registry["code.execute"](
            {
                "code": "raise ValueError('test error')",
            }
        )
        assert result["exit_code"] != 0
        assert "test error" in result["stderr"]


class TestToolsViaRPC:
    def test_tools_list(self) -> None:
        """List built-in tools."""
        registry = build_registry()
        result = registry["tools.list"]({})
        assert isinstance(result, list)
        # Should have the built-in tools
        assert len(result) > 0

    def test_tools_run_not_found(self) -> None:
        """Running a non-existent tool raises."""
        registry = build_registry()
        with pytest.raises(ValueError, match="not found"):
            registry["tools.run"](
                {
                    "name": "nonexistent_tool",
                    "data_path": "/tmp/fake.csv",
                    "params": {},
                }
            )


class TestEndToEndViaProtocol:
    def test_create_and_list_via_protocol(self, project_dir: Path) -> None:
        """Full round-trip through JSON-RPC protocol handler."""
        from urika.rpc.protocol import handle_request

        registry = build_registry()

        # Create experiment
        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "experiment.create",
                "params": {
                    "project_dir": str(project_dir),
                    "name": "E2E test",
                    "hypothesis": "End to end works",
                },
            }
        )
        resp = json.loads(handle_request(req, registry))
        assert "result" in resp
        assert resp["result"]["name"] == "E2E test"

        # List experiments
        req = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "experiment.list",
                "params": {"project_dir": str(project_dir)},
            }
        )
        resp = json.loads(handle_request(req, registry))
        assert len(resp["result"]) == 1
