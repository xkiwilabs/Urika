# Project Builder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an interactive project builder that scans data sources, profiles data, asks clarifying questions, and runs suggestion→planning loops with the user to scope projects before the first orchestrator run.

**Architecture:** `ProjectBuilder` class in `src/urika/core/project_builder.py` orchestrates the setup flow. It uses existing tools (data_profiler), knowledge pipeline (for ingesting papers/docs), and agent calls (via AgentRunner ABC) for question generation and planning. User interaction happens through Click prompts at the CLI level. Multi-file dataset support added to the data loader.

**Tech Stack:** Python, Click, pandas, dataclasses, existing Urika agent/tool/knowledge infrastructure

---

### Task 1: Add `description` field to ProjectConfig and update TOML serialization

**Files:**
- Modify: `src/urika/core/models.py`
- Modify: `tests/test_core/test_models.py`

**Step 1: Write failing tests**

Add to the existing `ProjectConfig` tests:

```python
def test_config_with_description(self) -> None:
    config = ProjectConfig(
        name="test", question="Q?", mode="exploratory",
        description="Predict target choices in herding task"
    )
    assert config.description == "Predict target choices in herding task"

def test_description_default_empty(self) -> None:
    config = ProjectConfig(name="test", question="Q?", mode="exploratory")
    assert config.description == ""

def test_description_roundtrips_via_toml(self) -> None:
    config = ProjectConfig(
        name="test", question="Q?", mode="exploratory",
        description="My project description"
    )
    d = config.to_toml_dict()
    restored = ProjectConfig.from_toml_dict(d)
    assert restored.description == "My project description"
```

**Step 2: Run tests — verify they fail**

Run: `pytest tests/test_core/test_models.py -v -k description`

**Step 3: Add `description` field to `ProjectConfig`**

In `src/urika/core/models.py`, add `description: str = ""` to `ProjectConfig`. Update `to_toml_dict()` to include it. Update `from_toml_dict()` to read it with `p.get("description", "")`.

**Step 4: Run tests — verify they pass**

Run: `pytest tests/test_core/test_models.py -v`

**Step 5: Commit**

```bash
git add src/urika/core/models.py tests/test_core/test_models.py
git commit -m "feat: add description field to ProjectConfig"
```

---

### Task 2: Add `load_dataset_directory()` to data loader

**Files:**
- Modify: `src/urika/data/loader.py`
- Modify: `src/urika/data/__init__.py`
- Create: `tests/test_data/test_directory_loader.py`

**Step 1: Write failing tests**

Create `tests/test_data/test_directory_loader.py`:

```python
"""Tests for directory-based dataset loading."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from urika.data.loader import load_dataset_directory


class TestLoadDatasetDirectory:
    def _make_csvs(self, tmp_path: Path, n: int = 3) -> Path:
        """Create n CSV files in a directory."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        for i in range(n):
            df = pd.DataFrame({"x": [i * 10 + j for j in range(5)], "y": [j for j in range(5)]})
            df.to_csv(data_dir / f"file_{i}.csv", index=False)
        return data_dir

    def test_loads_all_csvs(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 3)
        view = load_dataset_directory(data_dir)
        assert view.summary.n_rows == 15  # 3 files × 5 rows

    def test_adds_source_file_column(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 2)
        view = load_dataset_directory(data_dir)
        assert "_source_file" in view.data.columns

    def test_pattern_filter(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 3)
        # Add a non-matching file
        (data_dir / "notes.txt").write_text("not data")
        view = load_dataset_directory(data_dir, pattern="*.csv")
        assert view.summary.n_rows == 15

    def test_nested_glob(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        sub1 = data_dir / "group_a"
        sub2 = data_dir / "group_b"
        sub1.mkdir(parents=True)
        sub2.mkdir(parents=True)
        pd.DataFrame({"x": [1, 2]}).to_csv(sub1 / "f1.csv", index=False)
        pd.DataFrame({"x": [3, 4]}).to_csv(sub2 / "f2.csv", index=False)
        view = load_dataset_directory(data_dir, pattern="**/*.csv")
        assert view.summary.n_rows == 4

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError, match="No files found"):
            load_dataset_directory(empty)

    def test_nonexistent_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_dataset_directory(tmp_path / "nope")

    def test_spec_format_is_csv_directory(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 1)
        view = load_dataset_directory(data_dir)
        assert view.spec.format == "csv_directory"

    def test_returns_dataset_view(self, tmp_path: Path) -> None:
        data_dir = self._make_csvs(tmp_path, 1)
        view = load_dataset_directory(data_dir)
        from urika.data.models import DatasetView
        assert isinstance(view, DatasetView)
```

**Step 2: Run tests — verify they fail**

Run: `pytest tests/test_data/test_directory_loader.py -v`

**Step 3: Implement `load_dataset_directory()`**

Add to `src/urika/data/loader.py`:

```python
def load_dataset_directory(
    path: Path,
    pattern: str = "*.csv",
    name: str | None = None,
) -> DatasetView:
    """Load all matching files in a directory into a single DataFrame.

    Adds a '_source_file' column with the relative path of each source file.

    Raises:
        FileNotFoundError: If the directory does not exist.
        ValueError: If no files match the pattern.
    """
    import pandas as pd

    if not path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")

    files = sorted(path.glob(pattern))
    if not files:
        raise ValueError(f"No files found matching '{pattern}' in {path}")

    frames: list[pd.DataFrame] = []
    for f in files:
        df = pd.read_csv(f)
        df["_source_file"] = str(f.relative_to(path))
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    summary = profile_dataset(combined)
    spec = DatasetSpec(path=path, format="csv_directory", name=name or path.name)

    return DatasetView(spec=spec, data=combined, summary=summary)
```

**Step 4: Update `src/urika/data/__init__.py`**

Add `load_dataset_directory` to imports and `__all__`.

**Step 5: Run tests — verify they pass**

Run: `pytest tests/test_data/test_directory_loader.py -v`

**Step 6: Commit**

```bash
git add src/urika/data/loader.py src/urika/data/__init__.py tests/test_data/test_directory_loader.py
git commit -m "feat: add load_dataset_directory for multi-file datasets"
```

---

### Task 3: Source path scanner

**Files:**
- Create: `src/urika/core/source_scanner.py`
- Create: `tests/test_core/test_source_scanner.py`

**Step 1: Write failing tests**

```python
"""Tests for source path scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.core.source_scanner import scan_source_path, ScanResult


class TestScanSourcePath:
    def test_classifies_csv_files(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("x,y\n1,2\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 1

    def test_classifies_pdfs_as_papers(self, tmp_path: Path) -> None:
        (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        result = scan_source_path(tmp_path)
        assert len(result.papers) == 1

    def test_classifies_markdown_as_docs(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Title\n")
        result = scan_source_path(tmp_path)
        assert len(result.docs) == 1

    def test_classifies_python_as_code(self, tmp_path: Path) -> None:
        (tmp_path / "script.py").write_text("print('hello')\n")
        result = scan_source_path(tmp_path)
        assert len(result.code) == 1

    def test_nested_directories(self, tmp_path: Path) -> None:
        sub = tmp_path / "data" / "group1"
        sub.mkdir(parents=True)
        (sub / "trial1.csv").write_text("a,b\n1,2\n")
        (sub / "trial2.csv").write_text("a,b\n3,4\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 2

    def test_data_directories_grouped(self, tmp_path: Path) -> None:
        sub1 = tmp_path / "2Player"
        sub2 = tmp_path / "3Player"
        sub1.mkdir()
        sub2.mkdir()
        (sub1 / "t1.csv").write_text("x\n1\n")
        (sub2 / "t2.csv").write_text("x\n2\n")
        result = scan_source_path(tmp_path)
        assert len(result.data_directories) >= 2

    def test_single_file_path(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("x,y\n1,2\n")
        result = scan_source_path(f)
        assert len(result.data_files) == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = scan_source_path(tmp_path)
        assert len(result.data_files) == 0
        assert len(result.papers) == 0

    def test_summary_string(self, tmp_path: Path) -> None:
        (tmp_path / "data.csv").write_text("x\n1\n")
        (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4")
        result = scan_source_path(tmp_path)
        summary = result.summary()
        assert "1 data file" in summary or "Data files" in summary
```

**Step 2: Run tests — verify they fail**

Run: `pytest tests/test_core/test_source_scanner.py -v`

**Step 3: Implement source scanner**

Create `src/urika/core/source_scanner.py`:

```python
"""Scan a source path and classify files by type."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DATA_EXTENSIONS = {".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json", ".jsonl"}
DOC_EXTENSIONS = {".md", ".txt", ".rst", ".html"}
CODE_EXTENSIONS = {".py", ".r", ".jl", ".ipynb"}
PAPER_EXTENSIONS = {".pdf"}


@dataclass
class ScanResult:
    """Result of scanning a source path."""

    root: Path
    data_files: list[Path] = field(default_factory=list)
    data_directories: list[Path] = field(default_factory=list)
    docs: list[Path] = field(default_factory=list)
    papers: list[Path] = field(default_factory=list)
    code: list[Path] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable summary of what was found."""
        lines: list[str] = []
        if self.data_files:
            lines.append(f"Data files: {len(self.data_files)}")
            for d in self.data_directories:
                count = sum(1 for f in self.data_files if d in f.parents)
                lines.append(f"  {d.relative_to(self.root)}/ — {count} files")
        if self.docs:
            lines.append(f"Documentation: {len(self.docs)}")
            for d in self.docs:
                lines.append(f"  {d.relative_to(self.root)}")
        if self.papers:
            lines.append(f"Research papers: {len(self.papers)}")
            for p in self.papers:
                lines.append(f"  {p.relative_to(self.root)}")
        if self.code:
            lines.append(f"Code files: {len(self.code)}")
            for c in self.code:
                lines.append(f"  {c.relative_to(self.root)}")
        if not lines:
            lines.append("No recognized files found.")
        return "\n".join(lines)


def scan_source_path(path: Path) -> ScanResult:
    """Scan a path and classify all files by type.

    Accepts a file or directory. If a file, classifies just that file.
    """
    result = ScanResult(root=path if path.is_dir() else path.parent)

    if path.is_file():
        _classify_file(path, result)
        return result

    if not path.is_dir():
        return result

    data_dirs: set[Path] = set()
    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        _classify_file(f, result)
        if f.suffix.lower() in DATA_EXTENSIONS:
            data_dirs.add(f.parent)

    result.data_directories = sorted(data_dirs)
    return result


def _classify_file(f: Path, result: ScanResult) -> None:
    """Classify a single file into the appropriate list."""
    ext = f.suffix.lower()
    if ext in DATA_EXTENSIONS:
        result.data_files.append(f)
    elif ext in PAPER_EXTENSIONS:
        result.papers.append(f)
    elif ext in DOC_EXTENSIONS:
        result.docs.append(f)
    elif ext in CODE_EXTENSIONS:
        result.code.append(f)
```

**Step 4: Run tests — verify they pass**

Run: `pytest tests/test_core/test_source_scanner.py -v`

**Step 5: Commit**

```bash
git add src/urika/core/source_scanner.py tests/test_core/test_source_scanner.py
git commit -m "feat: add source path scanner for classifying files by type"
```

---

### Task 4: ProjectBuilder core class

**Files:**
- Create: `src/urika/core/project_builder.py`
- Create: `tests/test_core/test_project_builder.py`

**Step 1: Write failing tests**

```python
"""Tests for ProjectBuilder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from urika.core.project_builder import ProjectBuilder


class TestProjectBuilderInit:
    def test_creates_with_name_and_source(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test-project",
            source_path=source,
            projects_dir=tmp_path / "projects",
        )
        assert builder.name == "test-project"

    def test_scan_classifies_files(self, tmp_path: Path) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "data.csv").write_text("x,y\n1,2\n")
        (source / "README.md").write_text("# About\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        scan = builder.scan()
        assert len(scan.data_files) == 1
        assert len(scan.docs) == 1

    def test_profile_returns_summary(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n3,4\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects"
        )
        builder.scan()
        summary = builder.profile_data()
        assert summary.n_rows == 2

    def test_write_project_creates_workspace(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects",
            description="Test project", question="What?", mode="exploratory",
        )
        builder.scan()
        project_dir = builder.write_project()
        assert (project_dir / "urika.toml").exists()
        assert (project_dir / "experiments").is_dir()

    def test_write_project_stores_data_source(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects",
            description="Desc", question="Q?", mode="exploratory",
        )
        builder.scan()
        project_dir = builder.write_project()
        import tomllib
        with open(project_dir / "urika.toml", "rb") as f:
            data = tomllib.load(f)
        assert "data" in data

    def test_write_suggestions(self, tmp_path: Path) -> None:
        source = tmp_path / "data"
        source.mkdir()
        (source / "test.csv").write_text("x,y\n1,2\n")
        builder = ProjectBuilder(
            name="test", source_path=source, projects_dir=tmp_path / "projects",
            description="Desc", question="Q?", mode="exploratory",
        )
        builder.scan()
        builder.set_initial_suggestions({"suggestions": [{"name": "baseline"}]})
        project_dir = builder.write_project()
        suggestions_path = project_dir / "suggestions" / "initial.json"
        assert suggestions_path.exists()
        data = json.loads(suggestions_path.read_text())
        assert "suggestions" in data
```

**Step 2: Run tests — verify they fail**

Run: `pytest tests/test_core/test_project_builder.py -v`

**Step 3: Implement ProjectBuilder**

Create `src/urika/core/project_builder.py`:

```python
"""Interactive project builder — scans data, profiles, scopes projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.core.models import ProjectConfig
from urika.core.source_scanner import ScanResult, scan_source_path
from urika.core.workspace import create_project_workspace, _write_toml
from urika.data.models import DataSummary


class ProjectBuilder:
    """Orchestrates interactive project setup.

    Pure Urika code — no SDK imports. Agent calls go through AgentRunner
    passed to individual methods, user I/O goes through the CLI layer.
    """

    def __init__(
        self,
        name: str,
        source_path: Path,
        projects_dir: Path,
        *,
        description: str = "",
        question: str = "",
        mode: str = "exploratory",
    ) -> None:
        self.name = name
        self.source_path = source_path
        self.projects_dir = projects_dir
        self.description = description
        self.question = question
        self.mode = mode
        self._scan_result: ScanResult | None = None
        self._data_summary: DataSummary | None = None
        self._suggestions: dict[str, Any] | None = None
        self._tasks: list[dict[str, Any]] = []

    def scan(self) -> ScanResult:
        """Scan the source path and classify files."""
        self._scan_result = scan_source_path(self.source_path)
        return self._scan_result

    def profile_data(self, sample_limit: int = 5) -> DataSummary:
        """Profile a sample of data files."""
        from urika.data.profiler import profile_dataset
        import pandas as pd

        if self._scan_result is None:
            self.scan()
        assert self._scan_result is not None

        files = self._scan_result.data_files[:sample_limit]
        if not files:
            msg = "No data files found to profile"
            raise ValueError(msg)

        frames = []
        for f in files:
            try:
                frames.append(pd.read_csv(f))
            except Exception:
                continue

        if not frames:
            msg = "Could not read any data files"
            raise ValueError(msg)

        combined = pd.concat(frames, ignore_index=True)
        self._data_summary = profile_dataset(combined)
        return self._data_summary

    def set_initial_suggestions(self, suggestions: dict[str, Any]) -> None:
        """Store initial suggestions from the planning loop."""
        self._suggestions = suggestions

    def add_task(self, task: dict[str, Any]) -> None:
        """Add a scoped task to the initial task list."""
        self._tasks.append(task)

    def write_project(self) -> Path:
        """Write the project to disk and return the project directory."""
        project_dir = self.projects_dir / self.name

        config = ProjectConfig(
            name=self.name,
            question=self.question,
            mode=self.mode,
            description=self.description,
            data_paths=[str(self.source_path)],
        )
        create_project_workspace(project_dir, config)

        # Write data source config
        data_config = {
            "data": {
                "source": str(self.source_path),
                "format": self._detect_format(),
                "pattern": "**/*.csv",
            }
        }
        # Append data section to urika.toml
        import tomllib
        with open(project_dir / "urika.toml", "rb") as f:
            existing = tomllib.load(f)
        existing.update(data_config)
        _write_toml(project_dir / "urika.toml", existing)

        # Write initial suggestions if set
        if self._suggestions:
            suggestions_dir = project_dir / "suggestions"
            suggestions_dir.mkdir(exist_ok=True)
            (suggestions_dir / "initial.json").write_text(
                json.dumps(self._suggestions, indent=2) + "\n"
            )

        # Write initial tasks if any
        if self._tasks:
            tasks_dir = project_dir / "tasks"
            tasks_dir.mkdir(exist_ok=True)
            (tasks_dir / "initial.json").write_text(
                json.dumps(self._tasks, indent=2) + "\n"
            )

        return project_dir

    def _detect_format(self) -> str:
        """Detect data format from scan results."""
        if self._scan_result is None:
            return "unknown"
        exts = {f.suffix.lower() for f in self._scan_result.data_files}
        if len(self._scan_result.data_files) > 1:
            if ".csv" in exts:
                return "csv_directory"
            return "mixed_directory"
        if len(self._scan_result.data_files) == 1:
            return self._scan_result.data_files[0].suffix.lstrip(".").lower()
        return "unknown"
```

**Step 4: Run tests — verify they pass**

Run: `pytest tests/test_core/test_project_builder.py -v`

**Step 5: Commit**

```bash
git add src/urika/core/project_builder.py tests/test_core/test_project_builder.py
git commit -m "feat: add ProjectBuilder core class"
```

---

### Task 5: Update `urika new` CLI to use ProjectBuilder

**Files:**
- Modify: `src/urika/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Update the `new` command**

Modify the `urika new` CLI command to:
- Accept `--data` as either a file or directory path
- Accept `--description` for the project description
- Use `ProjectBuilder` to scan the source path
- Print the scan summary
- Ask "Is [path] the primary dataset?" via Click confirm
- Ask "Should I ingest documentation and papers into the knowledge base?" via Click confirm
- If knowledge ingestion approved, call `KnowledgeStore.ingest()` for docs/papers
- Profile data, print summary
- Write the project

This is the non-interactive version — the full agent-driven interactive loop (suggestion→planning with user refinement) will be added in Task 6. This task just wires up the builder with basic CLI prompts.

**Step 2: Write tests for the updated CLI**

Test that `urika new` with `--data` pointing to a directory creates a project with the correct data source config. Test that `--description` is stored.

**Step 3: Run tests — verify they pass**

Run: `pytest tests/test_cli.py -v -k "new"`

**Step 4: Commit**

```bash
git add src/urika/cli.py tests/test_cli.py
git commit -m "feat: update urika new CLI to use ProjectBuilder with data scanning"
```

---

### Task 6: Interactive planning loop in CLI

**Files:**
- Modify: `src/urika/cli.py`
- Create: `src/urika/core/builder_prompts.py`

**Step 1: Create builder prompts module**

Create `src/urika/core/builder_prompts.py` with functions that generate prompts for the project builder agent calls:

- `build_scoping_prompt(scan_result, data_summary, description)` — generates a prompt for the agent to produce clarifying questions based on data profile and description
- `build_suggestion_prompt(context)` — generates a prompt for the suggestion agent with accumulated context
- `build_planning_prompt(suggestions, context)` — generates a prompt for the planning agent

These are pure string-building functions — no SDK dependencies.

**Step 2: Add interactive loop to `urika new`**

After scanning and profiling, if `AgentRunner` is available:
1. Call agent with scoping prompt → get clarifying questions
2. Print questions one at a time, collect user answers via Click
3. Call suggestion agent → get initial suggestions
4. Call planning agent → get initial plan
5. Print plan to user
6. Loop: user types refinements or 'ok'
7. On 'ok', store suggestions and write project

If no agent runner available (no Claude SDK), skip the interactive loop and just write the project with what we have.

**Step 3: Write tests**

Test the prompt building functions (pure string functions, easy to test). The interactive loop itself is hard to unit test (requires mocking Click prompts and agent runners), so test it at a higher level with integration tests.

**Step 4: Run tests — verify they pass**

Run: `pytest tests/test_core/test_builder_prompts.py -v`

**Step 5: Commit**

```bash
git add src/urika/core/builder_prompts.py src/urika/cli.py tests/test_core/test_builder_prompts.py
git commit -m "feat: add interactive planning loop to project builder"
```

---

### Task 7: Project builder agent prompt

**Files:**
- Create: `src/urika/agents/roles/project_builder.py`
- Create: `src/urika/agents/roles/prompts/project_builder_system.md`
- Create: `tests/test_agents/test_project_builder_role.py`

**Step 1: Create the project builder prompt**

Create `src/urika/agents/roles/prompts/project_builder_system.md` — the system prompt for agent calls during project setup. It should instruct the agent to:
- Analyze the data profile and scan results
- Generate relevant clarifying questions one at a time
- Focus on: what to predict/analyse, how to define labels if missing, success criteria, data splits, initial approach
- Output questions as a JSON block for structured parsing

**Step 2: Create the role module**

Create `src/urika/agents/roles/project_builder.py` following the same pattern as other roles. Read-only agent (like evaluator), allowed tools: Read, Glob, Grep. No bash, no writes.

**Step 3: Write tests**

Follow the same pattern as `tests/test_agents/test_planning_agent_role.py` — test role discovery, config type, read-only security, prompt content.

**Step 4: Run tests — verify they pass**

Run: `pytest tests/test_agents/ -v`

**Step 5: Commit**

```bash
git add src/urika/agents/roles/project_builder.py src/urika/agents/roles/prompts/project_builder_system.md tests/test_agents/test_project_builder_role.py
git commit -m "feat: add project builder agent role and prompt"
```

---

### Task 8: Update docs and run full test suite

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `current-status.md`

**Step 1: Update CLAUDE.md**

- Add `src/urika/core/project_builder.py` to core modules
- Add `src/urika/core/source_scanner.py` to core modules
- Update `urika new` description to mention interactive builder
- Update project status with new test count

**Step 2: Update README.md**

- Update the `urika new` CLI reference to show `--data` and `--description` options
- Add brief mention that project builder scans data sources and can ingest docs/papers

**Step 3: Update current-status.md**

- Update test count
- Update tools count (16)
- Add project builder to "What's Built" section
- Update next steps (project builder is done, move to first real test)

**Step 4: Run full test suite**

Run: `pytest -v`
Run: `ruff check src/ tests/ && ruff format --check src/ tests/`
Expected: ALL PASS, clean

**Step 5: Commit**

```bash
git add CLAUDE.md README.md current-status.md
git commit -m "docs: update docs for project builder and multi-file datasets"
```
