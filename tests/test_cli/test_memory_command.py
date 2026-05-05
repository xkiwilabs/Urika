"""Tests for ``urika memory`` — v0.4.2 H12 regression suite.

Pre-v0.4.2 ``cli/memory.py`` (178 LOC, v0.4 Track 2 flagship feature)
had no test coverage. This file pins behaviour for ``list``, ``show``,
``add``, and ``delete`` so future edits surface regressions early.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core.models import ProjectConfig
from urika.core.workspace import create_project_workspace
from urika.core.registry import ProjectRegistry


def _setup(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "memproj"
    config = ProjectConfig(
        name="memproj",
        question="q",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(project_dir, config)
    ProjectRegistry().register("memproj", project_dir)
    return project_dir


class TestMemoryList:
    def test_empty_project(self, tmp_path: Path, monkeypatch) -> None:
        _setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "list", "memproj"])
        assert result.exit_code == 0, result.output
        assert "No memory entries" in result.output

    def test_empty_project_json(self, tmp_path: Path, monkeypatch) -> None:
        _setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "list", "memproj", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["project"] == "memproj"
        assert data["entries"] == []

    def test_list_after_add(self, tmp_path: Path, monkeypatch) -> None:
        project_dir = _setup(tmp_path, monkeypatch)
        # Seed an entry directly via the public API the CLI uses.
        from urika.core.project_memory import save_entry

        save_entry(
            project_dir,
            mem_type="feedback",
            body="user prefers seaborn over matplotlib",
            description="user prefers seaborn",
            slug="plotting_pref",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "list", "memproj"])
        assert result.exit_code == 0, result.output
        assert "plotting_pref" in result.output
        assert "feedback" in result.output


class TestMemoryShow:
    def test_show_existing_entry(self, tmp_path: Path, monkeypatch) -> None:
        project_dir = _setup(tmp_path, monkeypatch)
        from urika.core.project_memory import save_entry

        path = save_entry(
            project_dir,
            mem_type="instruction",
            body="always use cross-validation",
            description="cv-required",
            slug="cv_required",
        )

        # save_entry produces ``<type>_<slug>.md``; show accepts either
        # the full filename or a slug-prefix glob — we exercise both.
        runner = CliRunner()
        result = runner.invoke(
            cli, ["memory", "show", "memproj", Path(path).stem]
        )
        assert result.exit_code == 0, result.output
        assert "always use cross-validation" in result.output

    def test_show_missing_entry_errors_cleanly(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(cli, ["memory", "show", "memproj", "nope"])
        assert result.exit_code != 0
        assert "no memory entry" in result.output.lower()

    def test_partial_match_via_glob(self, tmp_path: Path, monkeypatch) -> None:
        project_dir = _setup(tmp_path, monkeypatch)
        from urika.core.project_memory import save_entry

        save_entry(
            project_dir,
            mem_type="feedback",
            body="seaborn for charts",
            description="d",
            slug="feedback_methods_v2",
        )

        runner = CliRunner()
        # Partial prefix should resolve via glob — saved filename is
        # ``feedback_feedback_methods_v2.md`` (type prefix + slug).
        result = runner.invoke(
            cli, ["memory", "show", "memproj", "feedback_feedback_methods"]
        )
        assert result.exit_code == 0, result.output
        assert "seaborn" in result.output


class TestMemoryAdd:
    def test_add_from_file(self, tmp_path: Path, monkeypatch) -> None:
        _setup(tmp_path, monkeypatch)
        body_file = tmp_path / "body.md"
        body_file.write_text("captured constraint about gpu memory\n")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "memory", "add", "memproj", "gpu_constraint",
                "--type", "decision",
                "--from-file", str(body_file),
                "--description", "GPU memory limits",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Wrote" in result.output

        # Verify it now lists.
        result = runner.invoke(cli, ["memory", "list", "memproj"])
        assert "gpu_constraint" in result.output
        assert "decision" in result.output

    def test_add_from_stdin(self, tmp_path: Path, monkeypatch) -> None:
        _setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "memory", "add", "memproj", "from_stdin_topic",
                "--type", "instruction",
                "--stdin",
                "--description", "from stdin",
            ],
            input="content fed via stdin\n",
        )
        assert result.exit_code == 0, result.output

    def test_from_file_and_stdin_mutually_exclusive(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _setup(tmp_path, monkeypatch)
        body_file = tmp_path / "b.md"
        body_file.write_text("x")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "memory", "add", "memproj", "topic",
                "--from-file", str(body_file),
                "--stdin",
            ],
        )
        assert result.exit_code != 0
        assert "not both" in result.output.lower() or "both" in result.output.lower()


class TestMemoryDelete:
    def test_delete_with_force(self, tmp_path: Path, monkeypatch) -> None:
        project_dir = _setup(tmp_path, monkeypatch)
        from urika.core.project_memory import save_entry

        path = save_entry(
            project_dir,
            mem_type="reference",
            body="link to paper",
            description="paper",
            slug="paper_link",
        )
        filename = Path(path).name

        runner = CliRunner()
        result = runner.invoke(
            cli, ["memory", "delete", "memproj", filename, "--force"]
        )
        assert result.exit_code == 0, result.output
        assert "Trashed" in result.output

        # The original file should be gone but a copy lives under .trash/.
        assert not Path(path).exists()
        trash_dir = Path(path).parent / ".trash"
        assert trash_dir.exists()

    def test_delete_missing_filename(self, tmp_path: Path, monkeypatch) -> None:
        _setup(tmp_path, monkeypatch)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["memory", "delete", "memproj", "nope.md", "--force"]
        )
        assert result.exit_code != 0
        assert "no entry" in result.output.lower()
