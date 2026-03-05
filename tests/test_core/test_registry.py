"""Tests for the project registry."""

from pathlib import Path

from urika.core.registry import ProjectRegistry


class TestProjectRegistry:
    def test_register_project(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("sleep-study", Path("/home/user/projects/sleep-study"))
        assert reg.get("sleep-study") == Path("/home/user/projects/sleep-study")

    def test_list_empty(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        assert reg.list_all() == {}

    def test_list_projects(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("project-a", Path("/a"))
        reg.register("project-b", Path("/b"))
        projects = reg.list_all()
        assert len(projects) == 2
        assert "project-a" in projects
        assert "project-b" in projects

    def test_get_nonexistent(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        assert reg.get("nope") is None

    def test_remove_project(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("test", Path("/test"))
        reg.remove("test")
        assert reg.get("test") is None

    def test_persistence(self, tmp_urika_home: Path) -> None:
        """Registry survives re-instantiation."""
        reg1 = ProjectRegistry()
        reg1.register("test", Path("/test"))

        reg2 = ProjectRegistry()
        assert reg2.get("test") == Path("/test")

    def test_duplicate_name_overwrites(self, tmp_urika_home: Path) -> None:
        reg = ProjectRegistry()
        reg.register("test", Path("/old"))
        reg.register("test", Path("/new"))
        assert reg.get("test") == Path("/new")
