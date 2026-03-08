"""Tests for knowledge integration in the orchestrator."""

from __future__ import annotations

from pathlib import Path

from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.orchestrator.knowledge import build_knowledge_summary


class TestBuildKnowledgeSummary:
    def test_returns_empty_when_no_knowledge(self, tmp_path: Path) -> None:
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        summary = build_knowledge_summary(project_dir)
        assert summary == ""

    def test_returns_summary_with_entries(self, tmp_path: Path) -> None:
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "notes.txt").write_text(
            "Regression is a key technique for prediction."
        )

        from urika.knowledge import KnowledgeStore

        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "notes.txt"))

        summary = build_knowledge_summary(project_dir)
        assert "notes.txt" in summary
        assert "Regression" in summary

    def test_truncates_long_content(self, tmp_path: Path) -> None:
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "long.txt").write_text("x" * 1000)

        from urika.knowledge import KnowledgeStore

        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "long.txt"))

        summary = build_knowledge_summary(project_dir)
        assert len(summary) < 1000

    def test_multiple_entries(self, tmp_path: Path) -> None:
        config = ProjectConfig(name="test", question="Q?", mode="exploratory")
        project_dir = tmp_path / "test"
        create_project_workspace(project_dir, config)

        knowledge_dir = project_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "a.txt").write_text("First note about alpha.")
        (knowledge_dir / "b.txt").write_text("Second note about beta.")

        from urika.knowledge import KnowledgeStore

        store = KnowledgeStore(project_dir)
        store.ingest(str(knowledge_dir / "a.txt"))
        store.ingest(str(knowledge_dir / "b.txt"))

        summary = build_knowledge_summary(project_dir)
        assert "a.txt" in summary
        assert "b.txt" in summary


class TestKnowledgePublicAPI:
    def test_build_knowledge_summary_importable(self) -> None:
        from urika.orchestrator import build_knowledge_summary

        assert callable(build_knowledge_summary)
