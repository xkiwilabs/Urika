"""Tests for the experiment trash/delete helper."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from urika.core.experiment_delete import (
    ActiveExperimentError,
    ExperimentNotFoundError,
    TrashExperimentResult,
    trash_experiment,
)


def _make_project_with_experiment(
    root: Path, project_name: str = "proj-foo", exp_id: str = "exp-001"
) -> tuple[Path, Path]:
    """Create a project + experiment tree on disk and return (project, exp)."""
    project = root / project_name
    project.mkdir()
    (project / "urika.toml").write_text(
        f'[project]\nname = "{project_name}"\n', encoding="utf-8"
    )
    exp_dir = project / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps({"experiment_id": exp_id, "name": "test"}), encoding="utf-8"
    )
    (exp_dir / "code").mkdir()
    (exp_dir / "code" / "run.py").write_text("print('x')\n", encoding="utf-8")
    return project, exp_dir


class TestTrashExperiment:
    def test_trash_moves_experiment_and_writes_manifest(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        project, exp_dir = _make_project_with_experiment(tmp_path)

        result = trash_experiment(project, "foo", "exp-001")

        assert isinstance(result, TrashExperimentResult)
        assert result.project_name == "foo"
        assert result.experiment_id == "exp-001"
        assert result.original_path == exp_dir
        # trash_path lives under <project>/trash/, NOT global ~/.urika/trash/
        assert result.trash_path.parent == project / "trash"
        assert result.trash_path.name.startswith("exp-001-")

        # Original experiment dir gone
        assert not exp_dir.exists()
        # Project + sibling dirs untouched
        assert project.exists()
        assert (project / "experiments").exists()

        # Trash folder exists with manifest at root
        assert result.trash_path.exists()
        manifest_path = result.trash_path / ".urika-trash-manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["kind"] == "experiment"
        assert manifest["project_name"] == "foo"
        assert manifest["experiment_id"] == "exp-001"
        assert manifest["original_path"] == str(exp_dir)
        assert "trashed_at" in manifest
        assert "urika_version" in manifest
        # Original code file moved into trash
        assert (result.trash_path / "code" / "run.py").exists()

        # Deletion log appended exactly once with kind=experiment
        log_path = tmp_urika_home / "deletion-log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["kind"] == "experiment"
        assert record["project_name"] == "foo"
        assert record["experiment_id"] == "exp-001"
        assert record["original_path"] == str(exp_dir)
        assert record["trash_path"] == str(result.trash_path)

    def test_trash_blocked_by_active_lock(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        import os

        project, exp_dir = _make_project_with_experiment(tmp_path)
        lock_path = exp_dir / ".lock"
        # Use the test process's own PID so it's guaranteed alive.
        lock_path.write_text(str(os.getpid()), encoding="utf-8")

        with pytest.raises(ActiveExperimentError) as excinfo:
            trash_experiment(project, "foo", "exp-001")

        assert str(lock_path) in str(excinfo.value)
        assert excinfo.value.lock_path == lock_path

        # Experiment dir untouched
        assert exp_dir.exists()
        # No manifest written
        assert not (exp_dir / ".urika-trash-manifest.json").exists()
        # Deletion log NOT created
        assert not (tmp_urika_home / "deletion-log.jsonl").exists()
        # No trash dir created either
        assert not (project / "trash").exists()

    def test_trash_ignores_stale_pid_lock(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        """A .lock file with a non-existent PID is stale and shouldn't block."""
        project, exp_dir = _make_project_with_experiment(tmp_path)
        # PID well outside the kernel's pid_max range — won't exist.
        (exp_dir / ".lock").write_text("9999999", encoding="utf-8")

        result = trash_experiment(project, "foo", "exp-001")

        assert result.trash_path.exists()
        assert not exp_dir.exists()

    def test_trash_ignores_empty_lock_file(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        """An empty .lock file (touched but never written) is stale."""
        project, exp_dir = _make_project_with_experiment(tmp_path)
        (exp_dir / ".lock").touch()

        result = trash_experiment(project, "foo", "exp-001")

        assert result.trash_path.exists()
        assert not exp_dir.exists()

    def test_trash_unknown_experiment_raises(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        project = tmp_path / "proj-foo"
        project.mkdir()
        (project / "experiments").mkdir()

        with pytest.raises(ExperimentNotFoundError):
            trash_experiment(project, "foo", "exp-missing")

    def test_trash_collision_within_same_second(
        self,
        tmp_path: Path,
        tmp_urika_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from urika.core import experiment_delete as ed

        monkeypatch.setattr(ed, "_timestamp", lambda: "20260426-100000")

        project, exp_dir = _make_project_with_experiment(tmp_path)
        result1 = trash_experiment(project, "foo", "exp-001")

        # Recreate the experiment dir and trash again within "the same second".
        exp_dir.mkdir(parents=True)
        (exp_dir / "experiment.json").write_text("{}", encoding="utf-8")
        result2 = trash_experiment(project, "foo", "exp-001")

        assert result1.trash_path.name == "exp-001-20260426-100000"
        assert result2.trash_path.name == "exp-001-20260426-100000-1"
        assert result1.trash_path != result2.trash_path
        assert result1.trash_path.exists()
        assert result2.trash_path.exists()

    def test_deletion_log_lines_are_valid_json(
        self, tmp_path: Path, tmp_urika_home: Path
    ) -> None:
        project, _exp1 = _make_project_with_experiment(tmp_path, "proj-foo", "exp-001")
        # Add a second experiment under the same project
        exp2 = project / "experiments" / "exp-002"
        exp2.mkdir()
        (exp2 / "experiment.json").write_text("{}", encoding="utf-8")

        trash_experiment(project, "foo", "exp-001")
        trash_experiment(project, "foo", "exp-002")

        log_path = tmp_urika_home / "deletion-log.jsonl"
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

        records = [json.loads(line) for line in lines]
        for rec in records:
            assert rec["kind"] == "experiment"
            assert set(
                [
                    "kind",
                    "project_name",
                    "experiment_id",
                    "original_path",
                    "trash_path",
                    "ts",
                ]
            ).issubset(rec.keys())

        ids = sorted(r["experiment_id"] for r in records)
        assert ids == ["exp-001", "exp-002"]

    def test_manifest_contents(self, tmp_path: Path, tmp_urika_home: Path) -> None:
        project, exp_dir = _make_project_with_experiment(tmp_path)

        result = trash_experiment(project, "foo", "exp-001")

        manifest_path = result.trash_path / ".urika-trash-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert set(
            [
                "kind",
                "project_name",
                "experiment_id",
                "original_path",
                "trashed_at",
                "urika_version",
            ]
        ).issubset(manifest.keys())
        assert manifest["kind"] == "experiment"
        assert manifest["project_name"] == "foo"
        assert manifest["experiment_id"] == "exp-001"
        assert manifest["original_path"] == str(exp_dir)
        # trashed_at parses as ISO datetime
        parsed = datetime.fromisoformat(manifest["trashed_at"])
        assert parsed is not None
