"""Tests for the project trash/delete helper."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from urika.core.project_delete import (
    ActiveRunError,
    ProjectNotFoundError,
    TrashResult,
    trash_project,
)
from urika.core.registry import ProjectRegistry


def _make_project(root: Path, name: str = "proj-foo") -> Path:
    """Create a small project tree with a file."""
    project = root / name
    project.mkdir()
    (project / "config.yaml").write_text("name: test\n", encoding="utf-8")
    (project / "experiments").mkdir()
    return project


class TestTrashProject:
    def test_trash_moves_folder_and_registers_manifest(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        project = _make_project(tmp_path, "proj-foo")
        registry = ProjectRegistry()
        registry.register("foo", project)

        result = trash_project("foo")

        assert isinstance(result, TrashResult)
        assert result.registry_only is False
        assert result.original_path == project
        assert result.trash_path is not None
        # trash_path lives under <URIKA_HOME>/trash/
        assert result.trash_path.parent == tmp_urika_home / "trash"
        assert result.trash_path.name.startswith("foo-")

        # Original folder gone
        assert not project.exists()

        # Trash folder exists with manifest
        assert result.trash_path.exists()
        manifest_path = result.trash_path / ".urika-trash-manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["registered_name"] == "foo"
        assert manifest["original_path"] == str(project)
        assert "trashed_at" in manifest
        assert "urika_version" in manifest

        # Registry no longer has the entry
        assert ProjectRegistry().get("foo") is None

        # Deletion log appended exactly once
        log_path = tmp_urika_home / "deletion-log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["name"] == "foo"
        assert record["registry_only"] is False

    def test_trash_missing_folder_is_registry_only(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        ghost = tmp_path / "does-not-exist"
        registry = ProjectRegistry()
        registry.register("ghost", ghost)

        result = trash_project("ghost")

        assert result.registry_only is True
        assert result.trash_path is None
        assert result.original_path == ghost

        # Registry cleared
        assert ProjectRegistry().get("ghost") is None

        # Deletion log appended
        log_path = tmp_urika_home / "deletion-log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["name"] == "ghost"
        assert record["registry_only"] is True
        assert record["trash_path"] is None

    def test_trash_blocked_by_active_lock(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        import os

        project = _make_project(tmp_path, "proj-locked")
        exp_dir = project / "experiments" / "exp-001"
        exp_dir.mkdir(parents=True)
        lock_path = exp_dir / ".lock"
        # Use the test process's own PID so it's guaranteed alive.
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

        registry = ProjectRegistry()
        registry.register("locked", project)

        with pytest.raises(ActiveRunError) as excinfo:
            trash_project("locked")

        assert str(lock_path) in str(excinfo.value)
        assert excinfo.value.lock_path == lock_path

        # Registry untouched
        assert ProjectRegistry().get("locked") == project
        # Folder untouched
        assert project.exists()
        # Deletion log NOT created
        assert not (tmp_urika_home / "deletion-log.jsonl").exists()
        # Manifest NOT written into the project
        assert not (project / ".urika-trash-manifest.json").exists()

    def test_trash_ignores_filelock_mutex_files(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        """JSON write mutexes (criteria.json.lock, usage.json.lock) are
        left around forever and don't indicate ongoing work — trashing
        must NOT block on them."""
        project = _make_project(tmp_path, "proj-mutex")
        # urika.core.filelock writes a sibling <name>.lock next to the
        # JSON file. These never get cleaned up and don't carry a PID.
        (project / "criteria.json.lock").touch()
        (project / "usage.json.lock").touch()

        registry = ProjectRegistry()
        registry.register("mutex", project)

        result = trash_project("mutex")
        assert result.registry_only is False
        assert result.trash_path is not None
        assert result.trash_path.exists()
        assert not project.exists()

    def test_trash_ignores_stale_pid_lock(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        """If a .lock file holds a PID that's no longer alive (process
        crashed without cleanup), it's stale and shouldn't block."""
        project = _make_project(tmp_path, "proj-stale")
        exp_dir = project / "experiments" / "exp-001"
        exp_dir.mkdir(parents=True)
        # PID well outside the kernel's pid_max range — won't exist.
        (exp_dir / ".lock").write_text("9999999", encoding="utf-8")

        registry = ProjectRegistry()
        registry.register("stale", project)

        result = trash_project("stale")
        assert result.registry_only is False
        assert result.trash_path is not None

    def test_trash_ignores_empty_lock_file(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        """Empty .lock files (touched but never written) are stale."""
        project = _make_project(tmp_path, "proj-empty")
        exp_dir = project / "experiments" / "exp-001"
        exp_dir.mkdir(parents=True)
        (exp_dir / ".lock").touch()

        registry = ProjectRegistry()
        registry.register("empty", project)

        result = trash_project("empty")
        assert result.registry_only is False

    def test_trash_unknown_project_raises(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        with pytest.raises(ProjectNotFoundError):
            trash_project("nonexistent")

    def test_trash_same_name_twice_distinct_paths(
        self,
        tmp_path: Path,
        tmp_urika_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from urika.core import project_delete

        timestamps = iter(["20260426-100000", "20260426-100005"])

        def fake_timestamp() -> str:
            return next(timestamps)

        monkeypatch.setattr(project_delete, "_timestamp", fake_timestamp)

        project = _make_project(tmp_path, "proj-twice")
        registry = ProjectRegistry()
        registry.register("twice", project)
        result1 = trash_project("twice")

        # Recreate folder + register
        project = _make_project(tmp_path, "proj-twice")
        registry = ProjectRegistry()
        registry.register("twice", project)
        result2 = trash_project("twice")

        assert result1.trash_path != result2.trash_path
        assert result1.trash_path.exists()
        assert result2.trash_path.exists()

    def test_trash_collision_within_same_second(
        self,
        tmp_path: Path,
        tmp_urika_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from urika.core import project_delete

        monkeypatch.setattr(project_delete, "_timestamp", lambda: "20260426-100000")

        project = _make_project(tmp_path, "proj-collide")
        registry = ProjectRegistry()
        registry.register("collide", project)
        result1 = trash_project("collide")

        project = _make_project(tmp_path, "proj-collide")
        registry = ProjectRegistry()
        registry.register("collide", project)
        result2 = trash_project("collide")

        assert result1.trash_path.name == "collide-20260426-100000"
        assert result2.trash_path.name == "collide-20260426-100000-1"
        assert result1.trash_path != result2.trash_path

    def test_deletion_log_lines_are_valid_json(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        # One normal trash
        project = _make_project(tmp_path, "proj-real")
        registry = ProjectRegistry()
        registry.register("real", project)
        trash_project("real")

        # One missing-folder trash
        ghost = tmp_path / "ghost-folder"
        registry = ProjectRegistry()
        registry.register("ghost", ghost)
        trash_project("ghost")

        log_path = tmp_urika_home / "deletion-log.jsonl"
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

        records = [json.loads(line) for line in lines]
        for rec in records:
            assert set(
                ["name", "original_path", "trash_path", "registry_only", "ts"]
            ).issubset(rec.keys())

        # First normal record: trash_path string, registry_only False
        normal = next(r for r in records if r["name"] == "real")
        assert isinstance(normal["trash_path"], str)
        assert normal["registry_only"] is False

        # Second ghost record: trash_path None, registry_only True
        ghost_rec = next(r for r in records if r["name"] == "ghost")
        assert ghost_rec["trash_path"] is None
        assert ghost_rec["registry_only"] is True

    def test_manifest_contents(self, tmp_path: Path, tmp_urika_home: Path) -> None:
        project = _make_project(tmp_path, "proj-manifest")
        registry = ProjectRegistry()
        registry.register("manifest", project)

        result = trash_project("manifest")

        manifest_path = result.trash_path / ".urika-trash-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert set(
            ["registered_name", "original_path", "trashed_at", "urika_version"]
        ).issubset(manifest.keys())
        assert manifest["registered_name"] == "manifest"
        assert manifest["original_path"] == str(project)
        # trashed_at parses as ISO datetime
        parsed = datetime.fromisoformat(manifest["trashed_at"])
        assert parsed is not None
