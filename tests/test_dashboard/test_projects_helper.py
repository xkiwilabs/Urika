"""Project-registry adapter for the dashboard v2.

Wraps the existing ProjectRegistry (~/.urika/projects.json) plus
on-disk project state so the dashboard pages have a single ergonomic
shape to consume.
"""

from __future__ import annotations

from pathlib import Path


from urika.dashboard.projects import (
    list_project_summaries,
    load_project_summary,
)


def _make_project(root: Path, name: str, *, with_experiment: bool = False) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\n'
        f'name = "{name}"\n'
        f'question = "test q"\n'
        f'mode = "exploratory"\n'
        f'description = ""\n'
        f'\n'
        f'[preferences]\n'
        f'audience = "expert"\n'
    )
    if with_experiment:
        exp_dir = proj / "experiments" / "exp-001"
        exp_dir.mkdir(parents=True)
        import json
        (exp_dir / "experiment.json").write_text(json.dumps({
            "experiment_id": "exp-001",
            "name": "baseline",
            "hypothesis": "test",
            "created": "2026-04-25T00:00:00Z",
        }))
        (exp_dir / "progress.json").write_text(json.dumps({
            "experiment_id": "exp-001",
            "status": "completed",
            "runs": [{"method": "ols", "metrics": {"r2": 0.5}}],
        }))
    return proj


def test_list_project_summaries_empty(tmp_path: Path):
    assert list_project_summaries({}) == []


def test_list_project_summaries_one_project(tmp_path: Path):
    proj = _make_project(tmp_path, "alpha")
    registry = {"alpha": proj}
    summaries = list_project_summaries(registry)
    assert len(summaries) == 1
    assert summaries[0].name == "alpha"
    assert summaries[0].path == proj
    assert summaries[0].experiment_count == 0


def test_list_project_summaries_with_experiment(tmp_path: Path):
    proj = _make_project(tmp_path, "alpha", with_experiment=True)
    registry = {"alpha": proj}
    summaries = list_project_summaries(registry)
    assert summaries[0].experiment_count == 1


def test_list_project_summaries_skips_missing_directory(tmp_path: Path):
    """Registry can point at a deleted project dir; surface it as
    'missing' rather than crashing."""
    registry = {"ghost": tmp_path / "does_not_exist"}
    summaries = list_project_summaries(registry)
    assert len(summaries) == 1
    assert summaries[0].missing is True


def test_load_project_summary_unknown_returns_none(tmp_path: Path):
    assert load_project_summary("nope", {}) is None


def test_load_project_summary_loads_full_metadata(tmp_path: Path):
    proj = _make_project(tmp_path, "alpha", with_experiment=True)
    registry = {"alpha": proj}
    summary = load_project_summary("alpha", registry)
    assert summary is not None
    assert summary.question == "test q"
    assert summary.mode == "exploratory"
