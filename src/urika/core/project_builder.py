"""Interactive project builder — scans data, profiles, scopes projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.core.models import ProjectConfig
from urika.core.source_scanner import ScanResult, scan_source_path
from urika.core.workspace import _write_toml, create_project_workspace
from urika.data.models import DataSummary


class ProjectBuilder:
    """Orchestrates interactive project setup.

    Pure Urika code — no SDK imports. Agent calls go through AgentRunner
    passed to individual methods, user I/O goes through the CLI layer.
    """

    def __init__(
        self,
        name: str,
        source_path: Path | None,
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
        self.web_search: bool = False
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
        import pandas as pd

        from urika.data.profiler import profile_dataset

        if self._scan_result is None:
            self.scan()
        assert self._scan_result is not None

        files = self._scan_result.data_files[:sample_limit]
        if not files:
            msg = "No data files found to profile"
            raise ValueError(msg)

        frames: list[pd.DataFrame] = []
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
        import tomllib

        project_dir = self.projects_dir / self.name

        data_paths = [str(self.source_path)] if self.source_path else []
        config = ProjectConfig(
            name=self.name,
            question=self.question,
            mode=self.mode,
            description=self.description,
            data_paths=data_paths,
        )
        create_project_workspace(project_dir, config)

        # Append data section and preferences to urika.toml
        with open(project_dir / "urika.toml", "rb") as f:
            existing = tomllib.load(f)

        if self.source_path:
            existing["data"] = {
                "source": str(self.source_path),
                "format": self._detect_format(),
                "pattern": "**/*.csv",
            }

        existing.setdefault("preferences", {})["web_search"] = self.web_search
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

        # Seed initial criteria
        from urika.core.criteria import append_criteria

        initial_criteria = {
            "type": "exploratory",
            "quality": {"min_approaches": 2},
            "completeness": ["establish baselines"],
        }
        append_criteria(
            project_dir,
            initial_criteria,
            set_by="project_builder",
            turn=0,
            rationale="Initial project criteria",
        )

        # Generate initial README.md
        from urika.core.readme_generator import write_readme

        write_readme(project_dir)

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
