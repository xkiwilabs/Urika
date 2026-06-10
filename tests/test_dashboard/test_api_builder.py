"""Tests for the dashboard's interactive builder wizard.

Covers two seams:

1. ``_DashboardBuilderShim`` — the ProjectBuilder-shaped adapter the
   dashboard hands to ``run_builder_loop``. It must persist research
   intent (refined question, preferences, hypotheses, co-drafted
   criteria) and the advisor suggestions exactly the way the CLI's
   real ``ProjectBuilder`` does. Pre-7.5 the shim only implemented
   ``set_initial_suggestions`` so the intent steps silently didn't
   persist on the dashboard surface.

2. The four wizard endpoints (``builder/start|stream|answer|abort``)
   driven end-to-end with a scripted agent runner through TestClient.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace


# ── 1. Shim persistence ────────────────────────────────────────────


@pytest.fixture
def scaffolded_project(tmp_path: Path, tmp_urika_home: Path) -> tuple[Path, Path]:
    """An on-disk workspace mirroring what POST /api/projects lays
    down before the wizard starts. Returns (projects_dir, project_dir)."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_dir = projects_dir / "alpha"
    create_project_workspace(
        project_dir,
        ProjectConfig(name="alpha", question="Original?", mode="exploratory"),
    )
    return projects_dir, project_dir


def _project_block(project_dir: Path) -> dict:
    with open(project_dir / "urika.toml", "rb") as f:
        return tomllib.load(f)["project"]


class TestDashboardBuilderShim:
    def test_shim_persists_research_intent_like_cli_builder(
        self, scaffolded_project
    ) -> None:
        """All the loop-gathered intent setters must round-trip to the
        on-disk project via apply_research_intent — same as the CLI."""
        from urika.dashboard.routers.api import _DashboardBuilderShim

        projects_dir, project_dir = scaffolded_project
        shim = _DashboardBuilderShim(name="alpha", projects_dir=projects_dir)

        shim.set_refined_question("Which features predict choice?")
        shim.set_research_preferences("statistical", "interpretable")
        shim.set_hypotheses(["H1: velocity predicts choice"])
        shim.set_initial_criteria(
            {
                "type": "exploratory",
                "quality": {"min_approaches": 2},
                "completeness": ["establish baselines"],
                "user_amendments": "also require cross-validation",
            }
        )
        shim.set_initial_suggestions(
            {"suggestions": [{"name": "rf-baseline", "method": "random forest"}]}
        )
        shim.apply_research_intent()

        block = _project_block(project_dir)
        assert block["question"] == "Which features predict choice?"
        assert block["analysis_approach"] == "statistical"
        assert block["interpretability_level"] == "interpretable"
        assert block["hypotheses"] == ["H1: velocity predicts choice"]

        from urika.core.criteria import load_criteria

        latest = load_criteria(project_dir)
        assert latest.criteria["user_amendments"] == "also require cross-validation"

        suggestions_path = project_dir / "suggestions" / "initial.json"
        assert suggestions_path.exists()
        sdata = json.loads(suggestions_path.read_text(encoding="utf-8"))
        assert sdata["suggestions"][0]["name"] == "rf-baseline"

    def test_shim_without_refinement_keeps_existing_question(
        self, scaffolded_project
    ) -> None:
        """The shim starts with an empty question, so apply_research_intent
        must NOT clobber the question already in urika.toml unless the
        feasibility step actually refined it."""
        from urika.dashboard.routers.api import _DashboardBuilderShim

        projects_dir, project_dir = scaffolded_project
        shim = _DashboardBuilderShim(name="alpha", projects_dir=projects_dir)
        shim.apply_research_intent()
        assert _project_block(project_dir)["question"] == "Original?"

    def test_shim_has_every_setter_the_loop_pushes(self) -> None:
        """``run_builder_loop`` pushes intent via duck-typed setters; a
        missing one is a silent no-persist. Pin the full set."""
        from urika.dashboard.routers.api import _DashboardBuilderShim

        for method in (
            "set_initial_suggestions",
            "set_refined_question",
            "set_research_preferences",
            "set_hypotheses",
            "set_initial_criteria",
            "apply_research_intent",
        ):
            assert callable(getattr(_DashboardBuilderShim, method, None)), (
                f"_DashboardBuilderShim is missing {method}"
            )
