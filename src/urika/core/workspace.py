"""Project workspace creation and loading."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from urika.core.models import ProjectConfig

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

    _write_toml(project_dir / "urika.toml", config.to_toml_dict())

    (project_dir / "leaderboard.json").write_text(
        json.dumps({"entries": []}, indent=2) + "\n"
    )

    (project_dir / "labbook" / "key-findings.md").write_text(
        f"# Key Findings: {config.name}\n\nNo findings yet.\n"
    )
    (project_dir / "labbook" / "results-summary.md").write_text(
        f"# Results Summary: {config.name}\n\nNo experiments completed yet.\n"
    )
    (project_dir / "labbook" / "progress-overview.md").write_text(
        f"# Progress Overview: {config.name}\n\n"
        f"**Question**: {config.question}\n\n"
        f"**Mode**: {config.mode}\n\nProject created. No experiments run yet.\n"
    )


def load_project_config(project_dir: Path) -> ProjectConfig:
    """Load a ProjectConfig from a project directory's urika.toml.

    Raises FileNotFoundError if the directory or toml doesn't exist.
    """
    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        msg = f"No urika.toml found at {toml_path}"
        raise FileNotFoundError(msg)

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
        items = ", ".join(f"{k} = {_toml_value(v)}" for k, v in val.items())
        return "{" + items + "}"
    return repr(val)
