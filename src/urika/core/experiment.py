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

    existing = sorted(d.name for d in experiments_dir.iterdir() if d.is_dir())
    if not existing:
        return "exp-001"

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

    (exp_dir / "experiment.json").write_text(config.to_json() + "\n")

    progress = {
        "experiment_id": experiment_id,
        "status": "pending",
        "runs": [],
    }
    (exp_dir / "progress.json").write_text(json.dumps(progress, indent=2) + "\n")

    (exp_dir / "labbook" / "notes.md").write_text(
        f"# Experiment: {name}\n\n**Hypothesis**: {hypothesis}\n\n"
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


def load_experiment(project_dir: Path, experiment_id: str) -> ExperimentConfig:
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
