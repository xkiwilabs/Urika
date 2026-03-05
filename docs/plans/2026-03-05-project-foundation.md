# Project Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the core project structure — data models, project registry, experiment lifecycle, labbook generation, and CLI — so that everything else (agents, evaluation, orchestrator) can build on a solid foundation.

**Architecture:** A `urika` Python package with Click CLI. Projects are directories with a `urika.toml` config. A central registry at `~/.urika/projects.json` tracks all projects. Experiments live inside projects. Runs are tracked in append-only `progress.json`. Labbook `.md` files are generated from run data. All state is filesystem-based (JSON + TOML + Markdown).

**Tech Stack:** Python 3.11+, click, tomli/tomllib, pytest, hatch (build), ruff (lint)

**Design doc:** `docs/plans/2026-03-05-project-structure-design.md`

---

### Task 1: Package Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/urika/__init__.py`
- Create: `src/urika/__main__.py`
- Create: `src/urika/cli.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "urika"
version = "0.1.0"
description = "Agentic scientific analysis platform"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "click>=8.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1",
]

[project.scripts]
urika = "urika.cli:cli"

[tool.hatch.build.targets.wheel]
packages = ["src/urika"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
target-version = "py311"
src = ["src"]
```

**Step 2: Create src/urika/__init__.py**

```python
"""Urika: Agentic scientific analysis platform."""

__version__ = "0.1.0"
```

**Step 3: Create src/urika/__main__.py**

```python
"""Allow running as `python -m urika`."""

from urika.cli import cli

cli()
```

**Step 4: Create src/urika/cli.py (minimal stub)**

```python
"""Urika CLI."""

import click


@click.group()
@click.version_option(package_name="urika")
def cli() -> None:
    """Urika: Agentic scientific analysis platform."""
```

**Step 5: Create tests/conftest.py**

```python
"""Shared test fixtures."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with minimal structure."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def tmp_urika_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary ~/.urika directory and patch URIKA_HOME."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(urika_home))
    return urika_home
```

**Step 6: Install package and verify**

Run: `pip install -e ".[dev]"`
Run: `python -c "import urika; print(urika.__version__)"`
Expected: `0.1.0`
Run: `urika --version`
Expected: prints version
Run: `pytest --co -q`
Expected: `no tests ran` (no test files yet)

**Step 7: Commit**

```bash
git add pyproject.toml src/ tests/conftest.py
git commit -m "feat: package skeleton with click CLI entry point"
```

---

### Task 2: Core Data Models

**Files:**
- Create: `src/urika/core/__init__.py`
- Create: `src/urika/core/models.py`
- Create: `tests/test_core/__init__.py`
- Create: `tests/test_core/test_models.py`

**Step 1: Write failing tests for data models**

```python
"""Tests for core data models."""

import json
from datetime import datetime, timezone

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
        import pytest

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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'urika.core'`

**Step 3: Implement the data models**

Create `src/urika/core/__init__.py` (empty).

Create `src/urika/core/models.py`:

```python
"""Core data models for Urika projects, experiments, and runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_MODES = {"exploratory", "confirmatory", "pipeline"}


@dataclass
class ProjectConfig:
    """Configuration for a Urika project. Serializes to/from urika.toml."""

    name: str
    question: str
    mode: str
    data_paths: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            msg = f"mode must be one of {VALID_MODES}, got '{self.mode}'"
            raise ValueError(msg)

    def to_toml_dict(self) -> dict[str, Any]:
        """Convert to a nested dict suitable for TOML serialization."""
        d: dict[str, Any] = {
            "project": {
                "name": self.name,
                "question": self.question,
                "mode": self.mode,
            }
        }
        if self.data_paths:
            d["project"]["data_paths"] = self.data_paths
        if self.success_criteria:
            d["project"]["success_criteria"] = self.success_criteria
        return d

    @classmethod
    def from_toml_dict(cls, d: dict[str, Any]) -> ProjectConfig:
        """Create from a parsed TOML dict."""
        p = d["project"]
        return cls(
            name=p["name"],
            question=p["question"],
            mode=p["mode"],
            data_paths=p.get("data_paths", []),
            success_criteria=p.get("success_criteria", {}),
        )


@dataclass
class ExperimentConfig:
    """Configuration for an experiment within a project."""

    experiment_id: str
    name: str
    hypothesis: str
    status: str = "pending"
    builds_on: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "status": self.status,
            "builds_on": self.builds_on,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExperimentConfig:
        return cls(
            experiment_id=d["experiment_id"],
            name=d["name"],
            hypothesis=d["hypothesis"],
            status=d.get("status", "pending"),
            builds_on=d.get("builds_on", []),
            created_at=d.get("created_at", ""),
        )


@dataclass
class RunRecord:
    """A single method execution within an experiment."""

    run_id: str
    method: str
    params: dict[str, Any]
    metrics: dict[str, float]
    hypothesis: str = ""
    observation: str = ""
    next_step: str = ""
    artifacts: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "method": self.method,
            "params": self.params,
            "metrics": self.metrics,
            "hypothesis": self.hypothesis,
            "observation": self.observation,
            "next_step": self.next_step,
            "artifacts": self.artifacts,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunRecord:
        return cls(
            run_id=d["run_id"],
            method=d["method"],
            params=d["params"],
            metrics=d["metrics"],
            hypothesis=d.get("hypothesis", ""),
            observation=d.get("observation", ""),
            next_step=d.get("next_step", ""),
            artifacts=d.get("artifacts", []),
            timestamp=d.get("timestamp", ""),
        )
```

Also create `tests/test_core/__init__.py` (empty).

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_models.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/core/ tests/test_core/
git commit -m "feat: core data models — ProjectConfig, ExperimentConfig, RunRecord"
```

---

### Task 3: Project Registry

**Files:**
- Create: `src/urika/core/registry.py`
- Create: `tests/test_core/test_registry.py`

**Step 1: Write failing tests**

```python
"""Tests for the project registry."""

from pathlib import Path

from urika.core.registry import ProjectRegistry


class TestProjectRegistry:
    def test_register_project(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("sleep-study", Path("/home/user/projects/sleep-study"))
        assert reg.get("sleep-study") == Path("/home/user/projects/sleep-study")

    def test_list_empty(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        assert reg.list_all() == {}

    def test_list_projects(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("project-a", Path("/a"))
        reg.register("project-b", Path("/b"))
        projects = reg.list_all()
        assert len(projects) == 2
        assert "project-a" in projects
        assert "project-b" in projects

    def test_get_nonexistent(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        assert reg.get("nope") is None

    def test_remove_project(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("test", Path("/test"))
        reg.remove("test")
        assert reg.get("test") is None

    def test_persistence(self, tmp_urika_home: Path) -> None:
        """Registry survives re-instantiation."""
        reg1 = ProjectRegistry()
        reg1.register("test", Path("/test"))

        reg2 = ProjectRegistry()
        assert reg2.get("test") == Path("/test")

    def test_duplicate_name_overwrites(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("test", Path("/old"))
        reg.register("test", Path("/new"))
        assert reg.get("test") == Path("/new")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the registry**

```python
"""Central project registry at ~/.urika/projects.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _urika_home() -> Path:
    """Return the Urika home directory, respecting URIKA_HOME env var."""
    env = os.environ.get("URIKA_HOME")
    if env:
        return Path(env)
    return Path.home() / ".urika"


class ProjectRegistry:
    """Manages the central registry of Urika projects."""

    def __init__(self) -> None:
        self._home = _urika_home()
        self._home.mkdir(parents=True, exist_ok=True)
        self._path = self._home / "projects.json"
        self._data = self._load()

    def _load(self) -> dict[str, str]:
        if self._path.exists():
            return json.loads(self._path.read_text())
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2) + "\n")

    def register(self, name: str, path: Path) -> None:
        """Register a project by name and path."""
        self._data[name] = str(path)
        self._save()

    def get(self, name: str) -> Path | None:
        """Get a project path by name, or None if not found."""
        raw = self._data.get(name)
        return Path(raw) if raw else None

    def remove(self, name: str) -> None:
        """Remove a project from the registry."""
        self._data.pop(name, None)
        self._save()

    def list_all(self) -> dict[str, Path]:
        """Return all registered projects as {name: path}."""
        return {k: Path(v) for k, v in self._data.items()}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_registry.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/core/registry.py tests/test_core/test_registry.py
git commit -m "feat: project registry — register, list, remove projects"
```

---

### Task 4: Project Workspace Creation

**Files:**
- Create: `src/urika/core/workspace.py`
- Create: `tests/test_core/test_workspace.py`

**Step 1: Write failing tests**

```python
"""Tests for project workspace creation."""

import json
from pathlib import Path

import pytest

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace, load_project_config


class TestCreateProjectWorkspace:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "sleep-study"
        config = ProjectConfig(
            name="sleep-study",
            question="What predicts sleep quality?",
            mode="exploratory",
        )
        create_project_workspace(project_dir, config)

        assert (project_dir / "urika.toml").exists()
        assert (project_dir / "data").is_dir()
        assert (project_dir / "tools").is_dir()
        assert (project_dir / "skills").is_dir()
        assert (project_dir / "methods").is_dir()
        assert (project_dir / "knowledge").is_dir()
        assert (project_dir / "experiments").is_dir()
        assert (project_dir / "labbook").is_dir()
        assert (project_dir / "config").is_dir()

    def test_writes_urika_toml(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test-project"
        config = ProjectConfig(
            name="test-project",
            question="Does X cause Y?",
            mode="confirmatory",
        )
        create_project_workspace(project_dir, config)

        loaded = load_project_config(project_dir)
        assert loaded.name == "test-project"
        assert loaded.mode == "confirmatory"

    def test_creates_empty_leaderboard(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(name="test", question="?", mode="exploratory")
        create_project_workspace(project_dir, config)

        lb = json.loads((project_dir / "leaderboard.json").read_text())
        assert lb == {"entries": []}

    def test_creates_labbook_stubs(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(name="test", question="?", mode="exploratory")
        create_project_workspace(project_dir, config)

        assert (project_dir / "labbook" / "key-findings.md").exists()
        assert (project_dir / "labbook" / "results-summary.md").exists()
        assert (project_dir / "labbook" / "progress-overview.md").exists()

    def test_raises_if_dir_exists(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "exists"
        project_dir.mkdir()
        (project_dir / "urika.toml").write_text("")

        config = ProjectConfig(name="exists", question="?", mode="exploratory")
        with pytest.raises(FileExistsError):
            create_project_workspace(project_dir, config)


class TestLoadProjectConfig:
    def test_load(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(
            name="test",
            question="Does X work?",
            mode="pipeline",
            data_paths=["data/input.csv"],
        )
        create_project_workspace(project_dir, config)

        loaded = load_project_config(project_dir)
        assert loaded.name == "test"
        assert loaded.mode == "pipeline"
        assert loaded.data_paths == ["data/input.csv"]

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_project_config(tmp_path / "nope")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_workspace.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement workspace creation**

```python
"""Project workspace creation and loading."""

from __future__ import annotations

import json
from pathlib import Path

from urika.core.models import ProjectConfig

# Directories created in every project workspace.
_PROJECT_DIRS = [
    "data",
    "tools",
    "skills",
    "methods",
    "knowledge",
    "knowledge/papers",
    "knowledge/notes",
    "experiments",
    "labbook",
    "config",
]


def create_project_workspace(project_dir: Path, config: ProjectConfig) -> None:
    """Create a project workspace directory with standard structure.

    Raises FileExistsError if the directory already contains a urika.toml.
    """
    if (project_dir / "urika.toml").exists():
        msg = f"Project already exists at {project_dir}"
        raise FileExistsError(msg)

    project_dir.mkdir(parents=True, exist_ok=True)

    for subdir in _PROJECT_DIRS:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Write urika.toml
    _write_toml(project_dir / "urika.toml", config.to_toml_dict())

    # Write empty leaderboard
    (project_dir / "leaderboard.json").write_text(
        json.dumps({"entries": []}, indent=2) + "\n"
    )

    # Write labbook stubs
    _write_labbook_stub(
        project_dir / "labbook" / "key-findings.md",
        f"# Key Findings: {config.name}\n\nNo findings yet.\n",
    )
    _write_labbook_stub(
        project_dir / "labbook" / "results-summary.md",
        f"# Results Summary: {config.name}\n\nNo experiments completed yet.\n",
    )
    _write_labbook_stub(
        project_dir / "labbook" / "progress-overview.md",
        f"# Progress Overview: {config.name}\n\n"
        f"**Question**: {config.question}\n\n"
        f"**Mode**: {config.mode}\n\nProject created. No experiments run yet.\n",
    )


def load_project_config(project_dir: Path) -> ProjectConfig:
    """Load a ProjectConfig from a project directory's urika.toml.

    Raises FileNotFoundError if the directory or toml doesn't exist.
    """
    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        msg = f"No urika.toml found at {toml_path}"
        raise FileNotFoundError(msg)

    import tomllib

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return ProjectConfig.from_toml_dict(data)


def _write_toml(path: Path, data: dict) -> None:
    """Write a dict as TOML. Minimal writer for simple nested dicts."""
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        if isinstance(values, dict):
            for key, val in values.items():
                lines.append(f"{key} = {_toml_value(val)}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def _toml_value(val: object) -> str:
    """Format a Python value as a TOML literal."""
    if isinstance(val, str):
        return f'"{val}"'
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        items = ", ".join(_toml_value(v) for v in val)
        return f"[{items}]"
    if isinstance(val, dict):
        # Inline table for simple dicts
        items = ", ".join(f"{k} = {_toml_value(v)}" for k, v in val.items())
        return "{" + items + "}"
    return repr(val)


def _write_labbook_stub(path: Path, content: str) -> None:
    path.write_text(content)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_workspace.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/core/workspace.py tests/test_core/test_workspace.py
git commit -m "feat: project workspace creation with directory structure and urika.toml"
```

---

### Task 5: Experiment Lifecycle

**Files:**
- Create: `src/urika/core/experiment.py`
- Create: `tests/test_core/test_experiment.py`

**Step 1: Write failing tests**

```python
"""Tests for experiment lifecycle."""

import json
from pathlib import Path

import pytest

from urika.core.experiment import (
    create_experiment,
    get_next_experiment_id,
    list_experiments,
    load_experiment,
)
from urika.core.models import ExperimentConfig, ProjectConfig
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a project workspace for testing."""
    d = tmp_path / "test-project"
    config = ProjectConfig(name="test", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


class TestGetNextExperimentId:
    def test_first_experiment(self, project_dir: Path) -> None:
        assert get_next_experiment_id(project_dir) == "exp-001"

    def test_increments(self, project_dir: Path) -> None:
        create_experiment(
            project_dir,
            name="Baseline",
            hypothesis="Test",
        )
        assert get_next_experiment_id(project_dir) == "exp-002"


class TestCreateExperiment:
    def test_creates_directory_structure(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Baseline linear models",
            hypothesis="Linear models establish a reasonable baseline",
        )

        exp_dir = project_dir / "experiments" / exp.experiment_id
        assert exp_dir.is_dir()
        assert (exp_dir / "experiment.json").exists()
        assert (exp_dir / "methods").is_dir()
        assert (exp_dir / "labbook").is_dir()
        assert (exp_dir / "artifacts").is_dir()
        assert (exp_dir / "progress.json").exists()

    def test_experiment_json_content(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Baseline",
            hypothesis="Linear models work",
        )
        exp_dir = project_dir / "experiments" / exp.experiment_id
        data = json.loads((exp_dir / "experiment.json").read_text())
        assert data["name"] == "Baseline"
        assert data["hypothesis"] == "Linear models work"
        assert data["status"] == "pending"

    def test_progress_json_initialized(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Test",
            hypothesis="Test",
        )
        exp_dir = project_dir / "experiments" / exp.experiment_id
        data = json.loads((exp_dir / "progress.json").read_text())
        assert data["experiment_id"] == exp.experiment_id
        assert data["runs"] == []

    def test_auto_slug_in_id(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir,
            name="Baseline Linear Models",
            hypothesis="Test",
        )
        assert exp.experiment_id.startswith("exp-001")
        assert "baseline-linear-models" in exp.experiment_id

    def test_with_builds_on(self, project_dir: Path) -> None:
        exp1 = create_experiment(
            project_dir, name="First", hypothesis="Test"
        )
        exp2 = create_experiment(
            project_dir,
            name="Second",
            hypothesis="Builds on first",
            builds_on=[exp1.experiment_id],
        )
        assert exp2.builds_on == [exp1.experiment_id]


class TestListExperiments:
    def test_empty(self, project_dir: Path) -> None:
        assert list_experiments(project_dir) == []

    def test_lists_all(self, project_dir: Path) -> None:
        create_experiment(project_dir, name="A", hypothesis="Test A")
        create_experiment(project_dir, name="B", hypothesis="Test B")
        experiments = list_experiments(project_dir)
        assert len(experiments) == 2

    def test_sorted_by_id(self, project_dir: Path) -> None:
        create_experiment(project_dir, name="A", hypothesis="Test")
        create_experiment(project_dir, name="B", hypothesis="Test")
        experiments = list_experiments(project_dir)
        assert experiments[0].experiment_id < experiments[1].experiment_id


class TestLoadExperiment:
    def test_load(self, project_dir: Path) -> None:
        exp = create_experiment(
            project_dir, name="Test", hypothesis="Test hypothesis"
        )
        loaded = load_experiment(project_dir, exp.experiment_id)
        assert loaded.name == "Test"
        assert loaded.hypothesis == "Test hypothesis"

    def test_load_nonexistent(self, project_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_experiment(project_dir, "exp-999-nope")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_experiment.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement experiment lifecycle**

```python
"""Experiment lifecycle: create, list, load experiments within a project."""

from __future__ import annotations

import json
import re
from pathlib import Path

from urika.core.models import ExperimentConfig


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug[:40].rstrip("-")


def get_next_experiment_id(project_dir: Path) -> str:
    """Return the next experiment ID (e.g., 'exp-001', 'exp-002')."""
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.exists():
        return "exp-001"

    existing = sorted(
        d.name for d in experiments_dir.iterdir() if d.is_dir()
    )
    if not existing:
        return "exp-001"

    # Extract the highest number from existing experiment IDs
    max_num = 0
    for name in existing:
        match = re.match(r"exp-(\d+)", name)
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"exp-{max_num + 1:03d}"


def create_experiment(
    project_dir: Path,
    *,
    name: str,
    hypothesis: str,
    builds_on: list[str] | None = None,
) -> ExperimentConfig:
    """Create a new experiment in a project.

    Creates the experiment directory structure and initial files.
    Returns the ExperimentConfig.
    """
    base_id = get_next_experiment_id(project_dir)
    slug = _slugify(name)
    experiment_id = f"{base_id}-{slug}" if slug else base_id

    config = ExperimentConfig(
        experiment_id=experiment_id,
        name=name,
        hypothesis=hypothesis,
        builds_on=builds_on or [],
    )

    exp_dir = project_dir / "experiments" / experiment_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "methods").mkdir()
    (exp_dir / "labbook").mkdir()
    (exp_dir / "artifacts").mkdir()

    # Write experiment.json
    (exp_dir / "experiment.json").write_text(config.to_json() + "\n")

    # Initialize progress.json
    progress = {
        "experiment_id": experiment_id,
        "status": "pending",
        "runs": [],
    }
    (exp_dir / "progress.json").write_text(
        json.dumps(progress, indent=2) + "\n"
    )

    # Initialize labbook stubs
    (exp_dir / "labbook" / "notes.md").write_text(
        f"# Experiment: {name}\n\n"
        f"**Hypothesis**: {hypothesis}\n\n"
    )

    return config


def list_experiments(project_dir: Path) -> list[ExperimentConfig]:
    """List all experiments in a project, sorted by ID."""
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.exists():
        return []

    configs = []
    for exp_dir in sorted(experiments_dir.iterdir()):
        json_path = exp_dir / "experiment.json"
        if json_path.exists():
            data = json.loads(json_path.read_text())
            configs.append(ExperimentConfig.from_dict(data))
    return configs


def load_experiment(
    project_dir: Path, experiment_id: str
) -> ExperimentConfig:
    """Load a specific experiment by ID.

    Raises FileNotFoundError if the experiment doesn't exist.
    """
    exp_dir = project_dir / "experiments" / experiment_id
    json_path = exp_dir / "experiment.json"
    if not json_path.exists():
        msg = f"Experiment {experiment_id} not found at {exp_dir}"
        raise FileNotFoundError(msg)

    data = json.loads(json_path.read_text())
    return ExperimentConfig.from_dict(data)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_experiment.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/core/experiment.py tests/test_core/test_experiment.py
git commit -m "feat: experiment lifecycle — create, list, load experiments"
```

---

### Task 6: Progress Tracking (Append-Only)

**Files:**
- Create: `src/urika/core/progress.py`
- Create: `tests/test_core/test_progress.py`

**Step 1: Write failing tests**

```python
"""Tests for append-only progress tracking."""

import json
from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import (
    append_run,
    get_best_run,
    load_progress,
    update_experiment_status,
)
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test"
    config = ProjectConfig(name="test", question="?", mode="exploratory")
    create_project_workspace(d, config)
    return d


@pytest.fixture
def experiment_id(project_dir: Path) -> str:
    exp = create_experiment(
        project_dir, name="Test", hypothesis="Test hypothesis"
    )
    return exp.experiment_id


class TestAppendRun:
    def test_append_single_run(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        run = RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.72},
        )
        append_run(project_dir, experiment_id, run)

        progress = load_progress(project_dir, experiment_id)
        assert len(progress["runs"]) == 1
        assert progress["runs"][0]["run_id"] == "run-001"

    def test_append_multiple_runs(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        for i in range(3):
            run = RunRecord(
                run_id=f"run-{i:03d}",
                method="test",
                params={},
                metrics={"r2": 0.1 * i},
            )
            append_run(project_dir, experiment_id, run)

        progress = load_progress(project_dir, experiment_id)
        assert len(progress["runs"]) == 3

    def test_append_is_additive(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        """Appending doesn't overwrite previous runs."""
        run1 = RunRecord(
            run_id="run-001", method="a", params={}, metrics={"r2": 0.5}
        )
        run2 = RunRecord(
            run_id="run-002", method="b", params={}, metrics={"r2": 0.7}
        )
        append_run(project_dir, experiment_id, run1)
        append_run(project_dir, experiment_id, run2)

        progress = load_progress(project_dir, experiment_id)
        assert progress["runs"][0]["method"] == "a"
        assert progress["runs"][1]["method"] == "b"


class TestGetBestRun:
    def test_best_run_higher_is_better(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        for i, r2 in enumerate([0.5, 0.9, 0.3]):
            run = RunRecord(
                run_id=f"run-{i:03d}",
                method="test",
                params={},
                metrics={"r2": r2},
            )
            append_run(project_dir, experiment_id, run)

        best = get_best_run(
            project_dir, experiment_id, metric="r2", direction="higher"
        )
        assert best is not None
        assert best["run_id"] == "run-001"
        assert best["metrics"]["r2"] == 0.9

    def test_best_run_lower_is_better(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        for i, rmse in enumerate([0.5, 0.1, 0.3]):
            run = RunRecord(
                run_id=f"run-{i:03d}",
                method="test",
                params={},
                metrics={"rmse": rmse},
            )
            append_run(project_dir, experiment_id, run)

        best = get_best_run(
            project_dir, experiment_id, metric="rmse", direction="lower"
        )
        assert best is not None
        assert best["metrics"]["rmse"] == 0.1

    def test_best_run_empty(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        best = get_best_run(
            project_dir, experiment_id, metric="r2", direction="higher"
        )
        assert best is None


class TestUpdateExperimentStatus:
    def test_update_status(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        update_experiment_status(project_dir, experiment_id, "in_progress")
        progress = load_progress(project_dir, experiment_id)
        assert progress["status"] == "in_progress"

    def test_update_to_completed(
        self, project_dir: Path, experiment_id: str
    ) -> None:
        update_experiment_status(project_dir, experiment_id, "completed")
        progress = load_progress(project_dir, experiment_id)
        assert progress["status"] == "completed"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_progress.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement progress tracking**

```python
"""Append-only progress tracking for experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.core.models import RunRecord


def _progress_path(project_dir: Path, experiment_id: str) -> Path:
    return project_dir / "experiments" / experiment_id / "progress.json"


def load_progress(project_dir: Path, experiment_id: str) -> dict[str, Any]:
    """Load progress.json for an experiment."""
    path = _progress_path(project_dir, experiment_id)
    return json.loads(path.read_text())


def _save_progress(
    project_dir: Path, experiment_id: str, data: dict[str, Any]
) -> None:
    path = _progress_path(project_dir, experiment_id)
    path.write_text(json.dumps(data, indent=2) + "\n")


def append_run(
    project_dir: Path, experiment_id: str, run: RunRecord
) -> None:
    """Append a run record to an experiment's progress.json."""
    data = load_progress(project_dir, experiment_id)
    data["runs"].append(run.to_dict())
    _save_progress(project_dir, experiment_id, data)


def get_best_run(
    project_dir: Path,
    experiment_id: str,
    *,
    metric: str,
    direction: str,
) -> dict[str, Any] | None:
    """Return the best run by a given metric.

    Args:
        metric: The metric name to compare.
        direction: 'higher' or 'lower'.

    Returns:
        The best run dict, or None if no runs exist.
    """
    data = load_progress(project_dir, experiment_id)
    runs = data.get("runs", [])
    if not runs:
        return None

    valid = [r for r in runs if metric in r.get("metrics", {})]
    if not valid:
        return None

    if direction == "higher":
        return max(valid, key=lambda r: r["metrics"][metric])
    return min(valid, key=lambda r: r["metrics"][metric])


def update_experiment_status(
    project_dir: Path, experiment_id: str, status: str
) -> None:
    """Update the status field in progress.json."""
    data = load_progress(project_dir, experiment_id)
    data["status"] = status
    _save_progress(project_dir, experiment_id, data)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_progress.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/core/progress.py tests/test_core/test_progress.py
git commit -m "feat: append-only progress tracking for experiment runs"
```

---

### Task 7: Labbook Generation

**Files:**
- Create: `src/urika/core/labbook.py`
- Create: `tests/test_core/test_labbook.py`

**Step 1: Write failing tests**

```python
"""Tests for labbook generation."""

from pathlib import Path

import pytest

from urika.core.experiment import create_experiment
from urika.core.labbook import (
    update_experiment_notes,
    generate_experiment_summary,
    generate_key_findings,
    generate_results_summary,
)
from urika.core.models import ProjectConfig, RunRecord
from urika.core.progress import append_run
from urika.core.workspace import create_project_workspace


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test"
    config = ProjectConfig(
        name="test-project",
        question="What predicts Y?",
        mode="exploratory",
    )
    create_project_workspace(d, config)
    return d


@pytest.fixture
def experiment_with_runs(project_dir: Path) -> str:
    exp = create_experiment(
        project_dir, name="Baseline", hypothesis="Linear models work"
    )
    eid = exp.experiment_id

    runs = [
        RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"alpha": 0.1},
            metrics={"r2": 0.72, "rmse": 0.15},
            hypothesis="Baseline linear model",
            observation="R2=0.72, nonlinearity in residuals",
            next_step="Try tree-based methods",
        ),
        RunRecord(
            run_id="run-002",
            method="ridge_regression",
            params={"alpha": 1.0},
            metrics={"r2": 0.73, "rmse": 0.14},
            hypothesis="Regularization helps",
            observation="Marginal improvement",
            next_step="Issue is model form, not overfitting",
        ),
    ]
    for run in runs:
        append_run(project_dir, eid, run)

    return eid


class TestUpdateExperimentNotes:
    def test_appends_run_notes(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        update_experiment_notes(project_dir, experiment_with_runs)

        notes_path = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "notes.md"
        )
        content = notes_path.read_text()
        assert "linear_regression" in content
        assert "ridge_regression" in content
        assert "R2=0.72" in content

    def test_includes_metrics(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        update_experiment_notes(project_dir, experiment_with_runs)

        notes_path = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "notes.md"
        )
        content = notes_path.read_text()
        assert "r2" in content
        assert "0.72" in content


class TestGenerateExperimentSummary:
    def test_generates_summary(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_experiment_summary(project_dir, experiment_with_runs)

        summary_path = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "summary.md"
        )
        assert summary_path.exists()
        content = summary_path.read_text()
        assert "Baseline" in content
        assert "run-001" in content or "linear_regression" in content

    def test_summary_includes_best_run(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_experiment_summary(project_dir, experiment_with_runs)

        summary_path = (
            project_dir
            / "experiments"
            / experiment_with_runs
            / "labbook"
            / "summary.md"
        )
        content = summary_path.read_text()
        # Best r2 is 0.73 from ridge_regression
        assert "0.73" in content


class TestGenerateResultsSummary:
    def test_generates_table(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_results_summary(project_dir)

        path = project_dir / "labbook" / "results-summary.md"
        content = path.read_text()
        assert "Baseline" in content
        assert "ridge_regression" in content or "0.73" in content


class TestGenerateKeyFindings:
    def test_generates_findings(
        self, project_dir: Path, experiment_with_runs: str
    ) -> None:
        generate_key_findings(project_dir)

        path = project_dir / "labbook" / "key-findings.md"
        content = path.read_text()
        assert "test-project" in content or "Key Findings" in content
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_core/test_labbook.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement labbook generation**

```python
"""Labbook generation: auto-generate .md summaries from progress data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.core.experiment import list_experiments, load_experiment
from urika.core.progress import load_progress


def update_experiment_notes(
    project_dir: Path, experiment_id: str
) -> None:
    """Regenerate the experiment's notes.md from progress.json runs."""
    exp = load_experiment(project_dir, experiment_id)
    progress = load_progress(project_dir, experiment_id)

    lines = [
        f"# Experiment: {exp.name}",
        "",
        f"**Hypothesis**: {exp.hypothesis}",
        "",
    ]

    for run in progress.get("runs", []):
        lines.append(f"## {run['run_id']}: {run['method']}")
        lines.append("")

        # Metrics
        metrics = run.get("metrics", {})
        if metrics:
            metric_strs = [f"{k}={v}" for k, v in metrics.items()]
            lines.append(f"**Metrics**: {', '.join(metric_strs)}")

        # Params
        params = run.get("params", {})
        if params:
            param_strs = [f"{k}={v}" for k, v in params.items()]
            lines.append(f"**Params**: {', '.join(param_strs)}")

        # Observations
        if run.get("hypothesis"):
            lines.append(f"- **Hypothesis**: {run['hypothesis']}")
        if run.get("observation"):
            lines.append(f"- **Observation**: {run['observation']}")
        if run.get("next_step"):
            lines.append(f"- **Next step**: {run['next_step']}")

        lines.append("")

    notes_path = (
        project_dir / "experiments" / experiment_id / "labbook" / "notes.md"
    )
    notes_path.write_text("\n".join(lines) + "\n")


def generate_experiment_summary(
    project_dir: Path, experiment_id: str
) -> None:
    """Generate a summary.md for a completed experiment."""
    exp = load_experiment(project_dir, experiment_id)
    progress = load_progress(project_dir, experiment_id)
    runs = progress.get("runs", [])

    lines = [
        f"# Experiment Summary: {exp.name}",
        "",
        f"**Hypothesis**: {exp.hypothesis}",
        f"**Runs**: {len(runs)}",
        "",
    ]

    if runs:
        # Find best run by first metric
        best = _find_best_run(runs)
        if best:
            lines.append(f"**Best run**: {best['run_id']} ({best['method']})")
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in best.get("metrics", {}).items()
            )
            lines.append(f"**Best metrics**: {metrics_str}")
            lines.append("")

        # Run table
        lines.append("| Run | Method | " + " | ".join(_all_metric_names(runs)) + " |")
        lines.append("|-----|--------|" + "|".join("---" for _ in _all_metric_names(runs)) + "|")
        for run in runs:
            metrics = run.get("metrics", {})
            row = f"| {run['run_id']} | {run['method']} | "
            row += " | ".join(
                str(metrics.get(m, "")) for m in _all_metric_names(runs)
            )
            row += " |"
            lines.append(row)
        lines.append("")

    # Key observations
    observations = [
        r["observation"] for r in runs if r.get("observation")
    ]
    if observations:
        lines.append("## Key Observations")
        lines.append("")
        for obs in observations:
            lines.append(f"- {obs}")
        lines.append("")

    summary_path = (
        project_dir / "experiments" / experiment_id / "labbook" / "summary.md"
    )
    summary_path.write_text("\n".join(lines) + "\n")


def generate_results_summary(project_dir: Path) -> None:
    """Generate the project-level results-summary.md."""
    experiments = list_experiments(project_dir)

    lines = [
        f"# Results Summary",
        "",
    ]

    if not experiments:
        lines.append("No experiments completed yet.")
    else:
        lines.append("| Experiment | Best Method | Runs | Key Metrics |")
        lines.append("|------------|-------------|------|-------------|")

        for exp in experiments:
            progress = load_progress(project_dir, exp.experiment_id)
            runs = progress.get("runs", [])
            best = _find_best_run(runs)

            method = best["method"] if best else "—"
            metrics_str = ""
            if best:
                metrics_str = ", ".join(
                    f"{k}={v}" for k, v in best.get("metrics", {}).items()
                )

            lines.append(
                f"| {exp.name} | {method} | {len(runs)} | {metrics_str} |"
            )
        lines.append("")

    path = project_dir / "labbook" / "results-summary.md"
    path.write_text("\n".join(lines) + "\n")


def generate_key_findings(project_dir: Path) -> None:
    """Generate the project-level key-findings.md."""
    from urika.core.workspace import load_project_config

    config = load_project_config(project_dir)
    experiments = list_experiments(project_dir)

    lines = [
        f"# Key Findings: {config.name}",
        "",
        f"**Question**: {config.question}",
        "",
    ]

    if not experiments:
        lines.append("No findings yet.")
    else:
        # Collect all runs across experiments, find overall best
        all_runs: list[tuple[str, dict[str, Any]]] = []
        for exp in experiments:
            progress = load_progress(project_dir, exp.experiment_id)
            for run in progress.get("runs", []):
                all_runs.append((exp.name, run))

        if all_runs:
            # Find best by first metric of first run
            best_exp_name, best_run = all_runs[0]
            if best_run.get("metrics"):
                first_metric = next(iter(best_run["metrics"]))
                for exp_name, run in all_runs:
                    if run.get("metrics", {}).get(first_metric, float("-inf")) > best_run["metrics"].get(first_metric, float("-inf")):
                        best_exp_name, best_run = exp_name, run

                metrics_str = ", ".join(
                    f"{k}={v}" for k, v in best_run["metrics"].items()
                )
                lines.append(
                    f"1. **Best result**: {best_run['method']} "
                    f"({metrics_str}) from {best_exp_name}"
                )

            lines.append(f"2. **Total runs**: {len(all_runs)} across {len(experiments)} experiments")
            lines.append("")

    path = project_dir / "labbook" / "key-findings.md"
    path.write_text("\n".join(lines) + "\n")


def _find_best_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the best run by the first metric (higher is better)."""
    if not runs:
        return None

    valid = [r for r in runs if r.get("metrics")]
    if not valid:
        return None

    first_metric = next(iter(valid[0]["metrics"]))
    return max(valid, key=lambda r: r["metrics"].get(first_metric, float("-inf")))


def _all_metric_names(runs: list[dict[str, Any]]) -> list[str]:
    """Collect all unique metric names across runs, preserving order."""
    seen: dict[str, None] = {}
    for run in runs:
        for key in run.get("metrics", {}):
            seen[key] = None
    return list(seen)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_core/test_labbook.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/core/labbook.py tests/test_core/test_labbook.py
git commit -m "feat: labbook generation — notes, summaries, key findings"
```

---

### Task 8: CLI Commands

**Files:**
- Modify: `src/urika/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write failing tests**

```python
"""Tests for the Urika CLI."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def urika_env(tmp_path: Path) -> dict[str, str]:
    """Environment with URIKA_HOME and URIKA_PROJECTS set."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }


class TestNewCommand:
    def test_creates_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "new",
                "sleep-study",
                "--question",
                "What predicts sleep quality?",
                "--mode",
                "exploratory",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        assert "Created project" in result.output

        # Verify project directory exists
        projects_dir = Path(urika_env["URIKA_PROJECTS_DIR"])
        assert (projects_dir / "sleep-study" / "urika.toml").exists()

    def test_registers_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        # Check registry
        reg_path = Path(urika_env["URIKA_HOME"]) / "projects.json"
        assert reg_path.exists()
        data = json.loads(reg_path.read_text())
        assert "test" in data

    def test_invalid_mode(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            ["new", "test", "-q", "?", "-m", "invalid"],
            env=urika_env,
        )
        assert result.exit_code != 0


class TestListCommand:
    def test_empty(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["list"], env=urika_env)
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_shows_projects(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "project-a", "-q", "Question A?", "-m", "exploratory"],
            env=urika_env,
        )
        runner.invoke(
            cli,
            ["new", "project-b", "-q", "Question B?", "-m", "confirmatory"],
            env=urika_env,
        )
        result = runner.invoke(cli, ["list"], env=urika_env)
        assert "project-a" in result.output
        assert "project-b" in result.output


class TestStatusCommand:
    def test_shows_status(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        runner.invoke(
            cli,
            ["new", "test", "-q", "Does X?", "-m", "exploratory"],
            env=urika_env,
        )
        result = runner.invoke(
            cli, ["status", "test"], env=urika_env
        )
        assert result.exit_code == 0
        assert "test" in result.output
        assert "Does X?" in result.output

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["status", "nope"], env=urika_env
        )
        assert result.exit_code != 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — commands don't exist yet

**Step 3: Implement CLI commands**

Replace `src/urika/cli.py` with:

```python
"""Urika CLI."""

from __future__ import annotations

import os
from pathlib import Path

import click

from urika.core.experiment import list_experiments
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace, load_project_config


def _projects_dir() -> Path:
    """Default directory for new projects."""
    env = os.environ.get("URIKA_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path.home() / "urika-projects"


@click.group()
@click.version_option(package_name="urika")
def cli() -> None:
    """Urika: Agentic scientific analysis platform."""


@cli.command()
@click.argument("name")
@click.option("-q", "--question", required=True, help="Research question.")
@click.option(
    "-m",
    "--mode",
    required=True,
    type=click.Choice(["exploratory", "confirmatory", "pipeline"]),
    help="Investigation mode.",
)
@click.option("--data", multiple=True, help="Path(s) to data files.")
def new(name: str, question: str, mode: str, data: tuple[str, ...]) -> None:
    """Create a new project."""
    config = ProjectConfig(
        name=name,
        question=question,
        mode=mode,
        data_paths=list(data),
    )

    project_dir = _projects_dir() / name
    try:
        create_project_workspace(project_dir, config)
    except FileExistsError:
        raise click.ClickException(f"Project already exists at {project_dir}")

    registry = ProjectRegistry()
    registry.register(name, project_dir)

    click.echo(f"Created project '{name}' at {project_dir}")


@cli.command("list")
def list_cmd() -> None:
    """List all registered projects."""
    registry = ProjectRegistry()
    projects = registry.list_all()

    if not projects:
        click.echo("No projects registered.")
        return

    for name, path in projects.items():
        exists = "  " if path.exists() else "? "
        click.echo(f"{exists}{name}  {path}")


@cli.command()
@click.argument("name")
def status(name: str) -> None:
    """Show project status."""
    registry = ProjectRegistry()
    project_path = registry.get(name)

    if project_path is None:
        raise click.ClickException(f"Project '{name}' not found in registry.")

    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise click.ClickException(
            f"Project directory missing at {project_path}"
        )

    experiments = list_experiments(project_path)

    click.echo(f"Project: {config.name}")
    click.echo(f"Question: {config.question}")
    click.echo(f"Mode: {config.mode}")
    click.echo(f"Path: {project_path}")
    click.echo(f"Experiments: {len(experiments)}")

    if experiments:
        click.echo("")
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            n_runs = len(progress.get("runs", []))
            exp_status = progress.get("status", "unknown")
            click.echo(
                f"  {exp.experiment_id}: {exp.name} "
                f"[{exp_status}, {n_runs} runs]"
            )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: CLI commands — new, list, status"
```

---

### Task 9: Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
"""Integration test: full project lifecycle."""

import json
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core.experiment import create_experiment, list_experiments
from urika.core.labbook import (
    generate_experiment_summary,
    generate_key_findings,
    generate_results_summary,
    update_experiment_notes,
)
from urika.core.models import RunRecord
from urika.core.progress import append_run, get_best_run, load_progress
from urika.core.workspace import load_project_config


def test_full_lifecycle(tmp_path: Path) -> None:
    """End-to-end: create project -> experiments -> runs -> labbook."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    env = {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }
    runner = CliRunner()

    # 1. Create project via CLI
    result = runner.invoke(
        cli,
        [
            "new", "sleep-study",
            "-q", "What predicts sleep quality?",
            "-m", "exploratory",
        ],
        env=env,
    )
    assert result.exit_code == 0

    project_dir = projects_dir / "sleep-study"
    config = load_project_config(project_dir)
    assert config.name == "sleep-study"

    # 2. Create experiments
    exp1 = create_experiment(
        project_dir,
        name="Baseline linear models",
        hypothesis="Linear models establish floor",
    )
    exp2 = create_experiment(
        project_dir,
        name="Tree-based methods",
        hypothesis="Nonlinear models improve over baseline",
        builds_on=[exp1.experiment_id],
    )

    assert len(list_experiments(project_dir)) == 2

    # 3. Record runs in experiment 1
    runs_exp1 = [
        RunRecord(
            run_id="run-001",
            method="linear_regression",
            params={"fit_intercept": True},
            metrics={"r2": 0.72, "rmse": 0.15},
            hypothesis="Baseline linear",
            observation="Nonlinearity in residuals",
            next_step="Try regularization",
        ),
        RunRecord(
            run_id="run-002",
            method="ridge_regression",
            params={"alpha": 1.0},
            metrics={"r2": 0.73, "rmse": 0.14},
            hypothesis="Regularization helps",
            observation="Marginal improvement, issue is model form",
            next_step="Try tree-based methods",
        ),
    ]
    for run in runs_exp1:
        append_run(project_dir, exp1.experiment_id, run)

    # 4. Record runs in experiment 2
    runs_exp2 = [
        RunRecord(
            run_id="run-001",
            method="random_forest",
            params={"n_estimators": 100},
            metrics={"r2": 0.82, "rmse": 0.09},
            hypothesis="Random forest captures nonlinearity",
            observation="Big improvement over linear",
            next_step="Try XGBoost",
        ),
        RunRecord(
            run_id="run-002",
            method="xgboost",
            params={"max_depth": 5, "learning_rate": 0.1},
            metrics={"r2": 0.85, "rmse": 0.07},
            hypothesis="XGBoost further improves",
            observation="Best model so far, exercise and caffeine top features",
        ),
    ]
    for run in runs_exp2:
        append_run(project_dir, exp2.experiment_id, run)

    # 5. Verify progress tracking
    progress1 = load_progress(project_dir, exp1.experiment_id)
    assert len(progress1["runs"]) == 2

    best1 = get_best_run(
        project_dir, exp1.experiment_id, metric="r2", direction="higher"
    )
    assert best1 is not None
    assert best1["method"] == "ridge_regression"

    best2 = get_best_run(
        project_dir, exp2.experiment_id, metric="r2", direction="higher"
    )
    assert best2 is not None
    assert best2["method"] == "xgboost"

    # 6. Generate labbook
    update_experiment_notes(project_dir, exp1.experiment_id)
    update_experiment_notes(project_dir, exp2.experiment_id)
    generate_experiment_summary(project_dir, exp1.experiment_id)
    generate_experiment_summary(project_dir, exp2.experiment_id)
    generate_results_summary(project_dir)
    generate_key_findings(project_dir)

    # 7. Verify labbook content
    notes1 = (
        project_dir / "experiments" / exp1.experiment_id / "labbook" / "notes.md"
    ).read_text()
    assert "linear_regression" in notes1
    assert "ridge_regression" in notes1

    summary2 = (
        project_dir / "experiments" / exp2.experiment_id / "labbook" / "summary.md"
    ).read_text()
    assert "xgboost" in summary2 or "0.85" in summary2

    results = (project_dir / "labbook" / "results-summary.md").read_text()
    assert "Baseline" in results
    assert "Tree-based" in results

    findings = (project_dir / "labbook" / "key-findings.md").read_text()
    assert "Key Findings" in findings

    # 8. Verify CLI status
    result = runner.invoke(cli, ["status", "sleep-study"], env=env)
    assert result.exit_code == 0
    assert "sleep-study" in result.output
    assert "2" in result.output  # 2 experiments

    # 9. Verify list
    result = runner.invoke(cli, ["list"], env=env)
    assert "sleep-study" in result.output
```

**Step 2: Run the integration test**

Run: `pytest tests/test_integration.py -v`
Expected: PASS (all previous tasks should make this work)

**Step 3: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration test for full project lifecycle"
```

---

### Task 10: Final Cleanup

**Step 1: Run linter**

Run: `ruff check src/ tests/`
Fix any issues found.

**Step 2: Run formatter**

Run: `ruff format src/ tests/`

**Step 3: Run full test suite one more time**

Run: `pytest -v --tb=short`
Expected: All tests PASS

**Step 4: Update CLAUDE.md**

Update `CLAUDE.md` to reflect the new project structure, referencing the design doc and describing how to run tests.

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: lint, format, update CLAUDE.md"
```

---

## Summary

After completing all 10 tasks, the project will have:

- **Package**: `urika` installable via pip with Click CLI
- **Data models**: `ProjectConfig`, `ExperimentConfig`, `RunRecord`
- **Project registry**: Central `~/.urika/projects.json` with register/list/remove
- **Workspace creation**: Full directory structure with urika.toml, labbook stubs, leaderboard
- **Experiment lifecycle**: Create, list, load experiments with auto-incrementing IDs
- **Progress tracking**: Append-only `progress.json` with best-run queries
- **Labbook generation**: Per-experiment notes + summaries, project-level results + key findings
- **CLI**: `urika new`, `urika list`, `urika status`
- **Tests**: Unit + integration covering the full lifecycle

This foundation supports everything that comes next: agents, evaluation framework, orchestrator, tool system, knowledge pipeline.
