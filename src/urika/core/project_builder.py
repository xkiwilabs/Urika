"""Interactive project builder — scans data, profiles, scopes projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

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
        self.use_venv: bool = False
        self.privacy_mode: str = "open"
        self.private_endpoint_url: str = ""
        self.private_endpoint_key_env: str = ""
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
        if self._scan_result is None:
            raise RuntimeError("scan() must be called before profiling")

        files = self._scan_result.data_files[:sample_limit]
        if not files:
            msg = "No data files found to profile"
            raise ValueError(msg)

        frames: list[pd.DataFrame] = []
        for f in files:
            try:
                frames.append(_read_data_file(f))
            except Exception:
                continue

        if not frames:
            msg = "Could not read any data files"
            raise ValueError(msg)

        combined = pd.concat(frames, ignore_index=True)
        self._data_summary = profile_dataset(combined)
        return self._data_summary

    def profile_all_data(self) -> dict[str, dict]:
        """Profile all data types found in the scan."""
        from urika.data.profiler import (
            profile_audio,
            profile_images,
            profile_spatial,
            profile_timeseries,
        )

        profiles: dict[str, dict] = {}
        if self._scan_result is None:
            return profiles

        if self._scan_result.images:
            profiles["images"] = profile_images(self._scan_result.images)
        if self._scan_result.audio:
            profiles["audio"] = profile_audio(self._scan_result.audio)
        if self._scan_result.timeseries:
            profiles["timeseries"] = profile_timeseries(self._scan_result.timeseries)
        if self._scan_result.spatial:
            profiles["spatial"] = profile_spatial(self._scan_result.spatial)
        return profiles

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
                "pattern": self._detect_glob_pattern(),
            }
            # Record a SHA-256 of every data path so ``urika run``
            # can detect drift if the user edits the data between
            # experiments. Pre-v0.4 there was no record at all,
            # making "I re-ran the experiment with edited data and
            # got different numbers" an invisible failure mode.
            from urika.data.data_hash import hash_data_files

            data_hashes = hash_data_files(data_paths)
            if data_hashes:
                existing.setdefault("project", {})["data_hashes"] = data_hashes

        existing.setdefault("preferences", {})["web_search"] = self.web_search

        if self.privacy_mode != "open":
            privacy = existing.setdefault("privacy", {})
            privacy["mode"] = self.privacy_mode
            if self.private_endpoint_url:
                # Skip the duplicate write when the user's typed URL
                # matches a global [privacy.endpoints.private].base_url.
                # The runtime loader (commit 1) inherits the endpoint
                # from globals, so duplicating it in the project TOML
                # only causes drift when the global URL changes later.
                # Non-matching URL → still written as a project-local
                # override.
                from urika.core.settings import get_named_endpoints

                _global_private_url = ""
                for ep in get_named_endpoints():
                    if ep.get("name") == "private":
                        _global_private_url = (
                            ep.get("base_url") or ""
                        ).strip()
                        break

                if (
                    self.private_endpoint_url.strip()
                    != _global_private_url
                ):
                    endpoints = privacy.setdefault("endpoints", {})
                    endpoint = endpoints.setdefault("private", {})
                    endpoint["base_url"] = self.private_endpoint_url
                    if self.private_endpoint_key_env:
                        endpoint["api_key_env"] = self.private_endpoint_key_env

        if self.use_venv:
            existing.setdefault("environment", {})["venv"] = True

        # Apply global runtime defaults (model, backend) for the
        # project's privacy mode. ``get_default_runtime(mode)`` prefers
        # ``[runtime.modes.<mode>].model`` (the canonical write path
        # used by the dashboard Models tab and new CLI wizard) over the
        # legacy flat ``[runtime].model`` key.
        from urika.core.settings import get_default_runtime

        runtime_defaults = get_default_runtime(self.privacy_mode)
        if runtime_defaults.get("model"):
            existing.setdefault("runtime", {}).setdefault(
                "model", runtime_defaults["model"]
            )

        _write_toml(project_dir / "urika.toml", existing)

        if self.use_venv:
            from urika.core.venv import create_project_venv

            create_project_venv(project_dir)

        # Write initial suggestions if set
        if self._suggestions:
            suggestions_dir = project_dir / "suggestions"
            suggestions_dir.mkdir(exist_ok=True)
            (suggestions_dir / "initial.json").write_text(
                json.dumps(self._suggestions, indent=2) + "\n",
                encoding="utf-8",
            )

        # Write initial tasks if any
        if self._tasks:
            tasks_dir = project_dir / "tasks"
            tasks_dir.mkdir(exist_ok=True)
            (tasks_dir / "initial.json").write_text(
                json.dumps(self._tasks, indent=2) + "\n",
                encoding="utf-8",
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

    def _detect_glob_pattern(self) -> str:
        """Detect the appropriate glob pattern from scan results."""
        if self._scan_result is None or not self._scan_result.data_files:
            return "**/*.csv"
        exts = {f.suffix.lower() for f in self._scan_result.data_files}
        if len(exts) == 1:
            ext = next(iter(exts))
            return f"**/*{ext}"
        # Mixed formats — list all extensions found
        sorted_exts = sorted(exts)
        return "**/*{" + ",".join(sorted_exts) + "}"


def _read_data_file(f: Path) -> pd.DataFrame:
    """Read a data file using the appropriate pandas reader based on extension."""
    import pandas as pd

    ext = f.suffix.lower()
    if ext == ".tsv":
        return pd.read_csv(f, sep="\t")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(f)
    if ext == ".parquet":
        return pd.read_parquet(f)
    if ext in (".json", ".jsonl"):
        return pd.read_json(f)
    if ext in (".feather", ".arrow"):
        return pd.read_feather(f)
    if ext == ".sav":
        return pd.read_spss(f)
    if ext == ".dta":
        return pd.read_stata(f)
    # Default fallback (covers .csv and unknown extensions)
    return pd.read_csv(f)
