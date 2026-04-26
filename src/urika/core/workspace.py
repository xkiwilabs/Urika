"""Project workspace creation and loading."""

from __future__ import annotations

import tomllib
from pathlib import Path

from urika.core.models import ProjectConfig

_PROJECT_DIRS = [
    "data",
    "tools",
    "methods",
    "knowledge",
    "knowledge/papers",
    "knowledge/notes",
    "experiments",
    "projectbook",
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

    # Append privacy section comment for discoverability (opt-in)
    with open(project_dir / "urika.toml", "a", encoding="utf-8") as f:
        f.write(
            "# [privacy]\n"
            '# mode = "open"  # open | private | hybrid\n'
            "#\n"
            "# [privacy.endpoints.local]\n"
            '# base_url = "http://localhost:11434"\n'
            '# api_key_env = ""\n'
        )

    (project_dir / "projectbook" / "key-findings.md").write_text(
        f"# Key Findings: {config.name}\n\nNo findings yet.\n",
        encoding="utf-8",
    )
    (project_dir / "projectbook" / "results-summary.md").write_text(
        f"# Results Summary: {config.name}\n\nNo experiments completed yet.\n",
        encoding="utf-8",
    )
    (project_dir / "projectbook" / "progress-overview.md").write_text(
        f"# Progress Overview: {config.name}\n\n"
        f"**Question**: {config.question}\n\n"
        f"**Mode**: {config.mode}\n\nProject created. No experiments run yet.\n",
        encoding="utf-8",
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
    """Write a dict as TOML. Minimal writer for simple nested dicts.

    When the data carries a ``[privacy].mode`` of ``private`` or
    ``hybrid``, a comment block is prepended explaining that per-agent
    models and endpoints are live-inherited from
    ``~/.urika/settings.toml``.  Pure docs — runtime behavior is
    unchanged — but it stops users staring at a project urika.toml
    wondering why it has no ``[runtime.models.*]`` block.
    """
    lines: list[str] = []

    privacy = data.get("privacy", {}) if isinstance(data, dict) else {}
    privacy_mode = (
        privacy.get("mode") if isinstance(privacy, dict) else None
    )
    if privacy_mode in ("private", "hybrid"):
        lines.extend(
            [
                f"# Privacy mode: {privacy_mode}. Per-agent models and "
                "endpoints inherit from",
                f"# ~/.urika/settings.toml [runtime.modes.{privacy_mode}] "
                "and [privacy.endpoints.*]",
                "# unless overridden in this file.",
                "",
            ]
        )

    for section, values in data.items():
        lines.append(f"[{section}]")
        if isinstance(values, dict):
            for key, val in values.items():
                lines.append(f"{key} = {_toml_value(val)}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(val: object) -> str:
    """Format a Python value as a TOML literal."""
    if val is None:
        return '""'
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
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
