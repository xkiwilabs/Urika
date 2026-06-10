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


def default_initial_criteria() -> dict[str, Any]:
    """The seed criteria every new project starts from.

    Single source of truth for ``write_project`` / ``enrich_workspace``
    (non-interactive paths keep these verbatim) and the base proposal
    for the interactive loop's criteria co-draft step."""
    return {
        "type": "exploratory",
        "quality": {"min_approaches": 2},
        "completeness": ["establish baselines"],
    }


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
        # Research intent gathered by the interactive builder loop —
        # empty means the user skipped (or a non-interactive path).
        self.hypotheses: list[str] = []
        self.analysis_approach: str = ""
        self.interpretability_level: str = ""
        self.constraints: dict[str, str] = {}
        self._scan_result: ScanResult | None = None
        self._data_summary: DataSummary | None = None
        self._suggestions: dict[str, Any] | None = None
        self._initial_criteria: dict[str, Any] | None = None
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

    def set_refined_question(self, question: str) -> None:
        """Replace the research question with the loop-refined version
        (feasibility check / user rephrase in the interactive loop)."""
        q = (question or "").strip()
        if q:
            self.question = q

    def set_research_preferences(
        self, analysis_approach: str = "", interpretability_level: str = ""
    ) -> None:
        """Store the user's analysis/interpretability preferences from
        the interactive loop's fixed elicitation questions."""
        if analysis_approach:
            self.analysis_approach = analysis_approach
        if interpretability_level:
            self.interpretability_level = interpretability_level

    def set_constraints(self, constraints: dict[str, str]) -> None:
        """Store practical constraints from the interactive loop's fixed
        elicitation question."""
        if constraints:
            self.constraints = dict(constraints)

    def set_hypotheses(self, hypotheses: list[str]) -> None:
        """Store user-approved hypotheses from the interactive loop."""
        self.hypotheses = [str(h).strip() for h in hypotheses if str(h).strip()]

    def set_initial_criteria(self, criteria: dict[str, Any]) -> None:
        """Store the user-approved success criteria from the interactive
        loop's co-draft step."""
        if criteria:
            self._initial_criteria = dict(criteria)

    def apply_research_intent(self) -> None:
        """Re-apply research intent gathered by the interactive builder
        loop to the on-disk project.

        ``write_project()`` runs BEFORE the interactive loop in the
        ``urika new`` flow (the loop's agents need the workspace and the
        knowledge base on disk), so anything the loop learns afterwards
        — refined question, preferences, hypotheses, co-drafted criteria,
        advisor suggestions — would otherwise never reach ``urika.toml``
        / ``criteria.json`` / ``suggestions/initial.json``.
        Called best-effort from ``run_builder_loop``'s ``finally``; a
        no-op when the project hasn't been written yet.
        """
        import tomllib

        toml_path = self.projects_dir / self.name / "urika.toml"
        if not toml_path.exists():
            return
        with open(toml_path, "rb") as f:
            existing = tomllib.load(f)

        project = existing.setdefault("project", {})
        if self.question:
            project["question"] = self.question
        if self.hypotheses:
            project["hypotheses"] = self.hypotheses
        if self.analysis_approach:
            project["analysis_approach"] = self.analysis_approach
        if self.interpretability_level:
            project["interpretability_level"] = self.interpretability_level
        if self.constraints:
            project["constraints"] = self.constraints
        _write_toml(toml_path, existing)

        # Seed the user-approved criteria from the co-draft step.
        # write_project() already appended the hardcoded defaults before
        # the loop ran, so only append a new version when the co-draft
        # actually changed them (an unchanged "Accept" must not produce
        # a duplicate version).
        if self._initial_criteria:
            from urika.core.criteria import append_criteria, load_criteria

            project_dir = self.projects_dir / self.name
            latest = load_criteria(project_dir)
            if latest is None or latest.criteria != self._initial_criteria:
                append_criteria(
                    project_dir,
                    self._initial_criteria,
                    set_by="project_builder",
                    turn=0,
                    rationale="User-approved success criteria (builder co-draft)",
                )

        # Flush the advisor suggestions captured by the loop.
        # ``write_project()`` (which ran before the loop) only writes
        # ``suggestions/initial.json`` when ``_suggestions`` was already
        # set — which it never is on the interactive path — yet
        # ``cli/project_new`` reads that file for the "run the first
        # planned experiment" offer right after the loop returns.
        self._write_suggestions(self.projects_dir / self.name)

    def add_task(self, task: dict[str, Any]) -> None:
        """Add a scoped task to the initial task list."""
        self._tasks.append(task)

    def _write_suggestions(self, project_dir: Path) -> None:
        """Write ``_suggestions`` to ``suggestions/initial.json``.
        No-op when empty. Shared by ``write_project`` (non-interactive
        path) and ``apply_research_intent`` (interactive-loop flush)."""
        if not self._suggestions:
            return
        suggestions_dir = project_dir / "suggestions"
        suggestions_dir.mkdir(exist_ok=True)
        (suggestions_dir / "initial.json").write_text(
            json.dumps(self._suggestions, indent=2) + "\n",
            encoding="utf-8",
        )

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
            hypotheses=self.hypotheses,
            analysis_approach=self.analysis_approach,
            interpretability_level=self.interpretability_level,
            constraints=self.constraints,
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
                        _global_private_url = (ep.get("base_url") or "").strip()
                        break

                if self.private_endpoint_url.strip() != _global_private_url:
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
        self._write_suggestions(project_dir)

        # Write initial tasks if any
        if self._tasks:
            tasks_dir = project_dir / "tasks"
            tasks_dir.mkdir(exist_ok=True)
            (tasks_dir / "initial.json").write_text(
                json.dumps(self._tasks, indent=2) + "\n",
                encoding="utf-8",
            )

        # Seed initial criteria — the co-drafted version when the
        # interactive loop already ran (set_initial_criteria), the
        # hardcoded defaults otherwise (JSON mode, dashboard scaffold).
        from urika.core.criteria import append_criteria

        initial_criteria = self._initial_criteria or default_initial_criteria()
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


def enrich_workspace(
    project_dir: Path,
    data_paths: list[str],
    *,
    privacy_mode: str = "open",
) -> dict[str, Any]:
    """Run non-interactive scan + profile + knowledge ingestion on an
    already-created project workspace.

    Mirrors the subset of :meth:`ProjectBuilder.write_project` that
    doesn't require an interactive agent loop: appends the ``[data]``
    block, ``[project].data_hashes`` (drift detection), ``[runtime]``
    defaults, seeds initial criteria, regenerates README.md, and
    ingests any docs/papers found alongside the data into the
    knowledge store.

    Best-effort throughout — non-existent paths are skipped silently,
    per-file ingest errors don't abort the rest, and missing optional
    dependencies (e.g. scipy) won't crash the call. Used by the
    dashboard's POST /api/projects so dashboard-created projects
    don't end up as bare skeletons.
    """
    import tomllib

    from urika.core.source_scanner import scan_source_path

    summary: dict[str, Any] = {
        "scanned_path": None,
        "data_files": 0,
        "profiled": False,
        "knowledge_ingested": 0,
    }

    source_path: Path | None = None
    for raw in data_paths:
        candidate = Path(raw).expanduser()
        if candidate.exists():
            source_path = candidate
            break

    scan_result: ScanResult | None = None
    if source_path is not None:
        try:
            scan_result = scan_source_path(source_path)
            summary["scanned_path"] = str(source_path)
            summary["data_files"] = len(scan_result.data_files)
        except Exception:
            scan_result = None

    toml_path = project_dir / "urika.toml"
    with open(toml_path, "rb") as f:
        existing = tomllib.load(f)

    if scan_result is not None and scan_result.data_files:
        exts = {f.suffix.lower() for f in scan_result.data_files}
        if len(scan_result.data_files) > 1:
            data_format = "csv_directory" if ".csv" in exts else "mixed_directory"
        else:
            data_format = scan_result.data_files[0].suffix.lstrip(".").lower()
        if len(exts) == 1:
            pattern = f"**/*{next(iter(exts))}"
        else:
            pattern = "**/*{" + ",".join(sorted(exts)) + "}"
        existing["data"] = {
            "source": str(source_path),
            "format": data_format,
            "pattern": pattern,
        }

        try:
            from urika.data.data_hash import hash_data_files

            real_paths = [p for p in data_paths if Path(p).expanduser().exists()]
            hashes = hash_data_files(real_paths)
            if hashes:
                existing.setdefault("project", {})["data_hashes"] = hashes
        except Exception:
            pass

        try:
            import pandas as pd

            from urika.data.profiler import profile_dataset

            frames: list[pd.DataFrame] = []
            for f in scan_result.data_files[:5]:
                try:
                    frames.append(_read_data_file(f))
                except Exception:
                    continue
            if frames:
                profile_dataset(pd.concat(frames, ignore_index=True))
                summary["profiled"] = True
        except Exception:
            pass

    try:
        from urika.core.settings import get_default_runtime

        runtime_defaults = get_default_runtime(privacy_mode)
        if runtime_defaults.get("model"):
            existing.setdefault("runtime", {}).setdefault(
                "model", runtime_defaults["model"]
            )
    except Exception:
        pass

    _write_toml(toml_path, existing)

    if scan_result is not None and (scan_result.docs or scan_result.papers):
        try:
            from urika.knowledge import KnowledgeStore

            store = KnowledgeStore(project_dir)
            for f in scan_result.docs + scan_result.papers:
                try:
                    store.ingest(str(f))
                    summary["knowledge_ingested"] += 1
                except Exception:
                    continue
        except Exception:
            pass

    try:
        from urika.core.criteria import append_criteria, load_criteria_history

        if not load_criteria_history(project_dir):
            append_criteria(
                project_dir,
                default_initial_criteria(),
                set_by="project_builder",
                turn=0,
                rationale="Initial project criteria",
            )
    except Exception:
        pass

    try:
        from urika.core.readme_generator import write_readme

        write_readme(project_dir)
    except Exception:
        pass

    return summary


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
