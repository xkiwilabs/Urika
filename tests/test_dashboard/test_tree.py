"""Tests for dashboard project tree builder."""
from urika.dashboard.tree import build_project_tree


class TestBuildProjectTree:
    def test_has_experiments_section(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        labels = [s["label"] for s in tree]
        assert "Experiments" in labels

    def test_experiment_has_children(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        exp_section = next(s for s in tree if s["label"] == "Experiments")
        assert len(exp_section["children"]) == 1
        exp = exp_section["children"][0]
        assert "exp-001" in exp["label"]
        child_labels = [c["label"] for c in exp["children"]]
        assert "Labbook" in child_labels
        assert "Artifacts" in child_labels

    def test_labbook_has_files(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        exp_section = next(s for s in tree if s["label"] == "Experiments")
        exp = exp_section["children"][0]
        labbook = next(c for c in exp["children"] if c["label"] == "Labbook")
        file_labels = [f["label"] for f in labbook["children"]]
        assert "notes.md" in file_labels
        assert "summary.md" in file_labels

    def test_has_projectbook_section(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        labels = [s["label"] for s in tree]
        assert "Projectbook" in labels

    def test_has_methods_section(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        labels = [s["label"] for s in tree]
        assert "Methods" in labels

    def test_has_criteria_section(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        labels = [s["label"] for s in tree]
        assert "Criteria" in labels

    def test_artifacts_includes_images(self, dashboard_project):
        tree = build_project_tree(dashboard_project)
        exp_section = next(s for s in tree if s["label"] == "Experiments")
        exp = exp_section["children"][0]
        artifacts = next(c for c in exp["children"] if c["label"] == "Artifacts")
        file_labels = [f["label"] for f in artifacts["children"]]
        assert "results.png" in file_labels

    def test_empty_project(self, tmp_path):
        """Empty directory returns sections with empty children."""
        (tmp_path / "urika.toml").write_text(
            '[project]\nname = "empty"\nquestion = "q"\nmode = "exploratory"\n'
        )
        tree = build_project_tree(tmp_path)
        assert len(tree) > 0  # Still has section headers

    def test_presentation_is_link_type(self, dashboard_project):
        """Presentation entries have type 'link' for opening in new tab."""
        # Create a presentation index.html
        pres_dir = (
            dashboard_project / "experiments" / "exp-001-baseline" / "presentation"
        )
        (pres_dir / "index.html").write_text("<html></html>")
        tree = build_project_tree(dashboard_project)
        exp_section = next(s for s in tree if s["label"] == "Experiments")
        exp = exp_section["children"][0]
        pres = next(
            (c for c in exp["children"] if c["label"] == "Presentation"), None
        )
        assert pres is not None
        assert pres["type"] == "link"
