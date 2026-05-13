"""Integration test: seed a real project from a bundled test dataset.

``dev/test-datasets/<name>/`` ships a small real CSV under ``data/``
and a ``knowledge/data-description.md``. This runs the non-interactive
project-builder path (``create_project_workspace`` + ``enrich_workspace``
— scan → profile → data-hash → criteria → README → knowledge ingest;
no LLM / API call) against one of them and asserts the resulting
project is properly set up: a ``[data]`` block + drift hashes in
``urika.toml``, seeded criteria, a regenerated README, and the
description doc ingested into the knowledge store.

This is the same path the dashboard's ``POST /api/projects`` uses, so a
green run here means "create a project from a real dataset directory →
usable project, not a bare skeleton".

Marked ``integration`` because it reads ``dev/test-datasets/`` (not
shipped in the wheel) — skipped when that tree isn't present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_DATASETS_ROOT = Path(__file__).resolve().parent.parent / "dev" / "test-datasets"


def _dataset_dir(name: str) -> Path:
    d = _DATASETS_ROOT / name
    if not (d / "data").is_dir():
        pytest.skip(f"bundled test dataset '{name}' not present at {d}")
    return d


@pytest.mark.parametrize("dataset", ["stroop", "depression"])
def test_seed_project_from_bundled_dataset(tmp_path: Path, dataset: str) -> None:
    import json
    import tomllib

    from urika.core.models import ProjectConfig
    from urika.core.project_builder import enrich_workspace
    from urika.core.workspace import create_project_workspace
    from urika.knowledge import KnowledgeStore

    ds = _dataset_dir(dataset)

    project_dir = tmp_path / f"{dataset}-from-fixture"
    create_project_workspace(
        project_dir,
        ProjectConfig(
            name=f"{dataset}-from-fixture",
            question=f"What does the {dataset} dataset show?",
            mode="exploratory",
            data_paths=[str(ds)],
        ),
    )

    # The dashboard / `urika new --json` non-interactive enrichment pass,
    # pointed at the dataset *directory* (which contains data/*.csv +
    # knowledge/*.md).
    summary = enrich_workspace(project_dir, [str(ds)])

    # --- the scan found the real data file(s) ---
    assert summary["data_files"] >= 1, summary
    assert summary["scanned_path"] == str(ds)

    toml_data = tomllib.loads((project_dir / "urika.toml").read_text(encoding="utf-8"))
    assert "data" in toml_data, "urika.toml has no [data] block — scan/enrich failed"
    assert toml_data["data"]["source"] == str(ds)
    assert toml_data["data"]["format"], toml_data["data"]
    # Drift baseline recorded over the real file(s).
    assert toml_data.get("project", {}).get("data_hashes"), toml_data

    # --- initial criteria seeded ---
    crit = json.loads((project_dir / "criteria.json").read_text(encoding="utf-8"))
    versions = crit.get("versions", [])
    assert versions, "criteria.json has no versions"
    v0 = versions[0]
    assert v0.get("criteria"), "initial criteria version is empty"
    assert v0.get("set_by") == "project_builder"

    # --- README regenerated ---
    assert (project_dir / "README.md").exists()

    # --- the description doc was ingested into the knowledge store ---
    assert summary["knowledge_ingested"] >= 1, summary
    entries = KnowledgeStore(project_dir).list_all()
    assert entries, "knowledge store is empty after enrich_workspace"
    titles = " ".join((e.title or "") + " " + (e.source or "") for e in entries).lower()
    assert "data-description" in titles or "description" in titles, (
        f"expected the dataset's data-description doc among ingested entries; "
        f"got: {[e.title for e in entries]}"
    )


def test_seed_project_from_data_subdir_only(tmp_path: Path) -> None:
    """Pointing only at the ``data/`` subdir (no docs) still produces a
    usable project — just without knowledge ingestion."""
    import tomllib

    from urika.core.models import ProjectConfig
    from urika.core.project_builder import enrich_workspace
    from urika.core.workspace import create_project_workspace

    ds = _dataset_dir("stroop")
    project_dir = tmp_path / "stroop-dataonly"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="stroop-dataonly", question="Q?", mode="exploratory",
                      data_paths=[str(ds / "data")]),
    )
    summary = enrich_workspace(project_dir, [str(ds / "data")])
    assert summary["data_files"] >= 1
    toml_data = tomllib.loads((project_dir / "urika.toml").read_text(encoding="utf-8"))
    assert toml_data["data"]["source"] == str(ds / "data")
    assert toml_data["data"]["format"] == "csv"
    assert toml_data["data"]["pattern"] == "**/*.csv"
    assert (project_dir / "criteria.json").exists()
    assert (project_dir / "README.md").exists()
