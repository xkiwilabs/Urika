"""Tests for ``urika memory archive`` (v0.5.0 Task 3.2).

Lists archived memory entries (``memory/archive/<YYYY-MM>/``), with
optional ``--month YYYY-MM`` filter and ``--json`` output.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core import project_memory as pm
from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace


def _setup(tmp_path: Path, monkeypatch) -> Path:
    """Register a project named ``proj`` and return its dir."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    config = ProjectConfig(
        name="proj",
        question="q",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(project_dir, config)
    ProjectRegistry().register("proj", project_dir)
    return project_dir


def test_archive_lists_entries(tmp_path: Path, monkeypatch) -> None:
    """An archived entry should appear in the listing."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="t", body="b")
    name = pm.list_entries(project_dir)[0]["filename"]
    pm.archive_entry(project_dir, name)

    result = CliRunner().invoke(cli, ["memory", "archive", "proj"])
    assert result.exit_code == 0, result.output
    assert name in result.output


def test_archive_empty_message_when_none(tmp_path: Path, monkeypatch) -> None:
    """Empty archive prints a friendly message instead of nothing."""
    _setup(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["memory", "archive", "proj"])
    assert result.exit_code == 0, result.output
    assert "No archived" in result.output


def test_archive_month_filter(tmp_path: Path, monkeypatch) -> None:
    """``--month YYYY-MM`` filters to that month only."""
    project_dir = _setup(tmp_path, monkeypatch)
    md = pm.memory_dir(project_dir)
    (md / "archive" / "2024-01").mkdir(parents=True)
    (md / "archive" / "2024-02").mkdir(parents=True)
    (md / "archive" / "2024-01" / "user_jan.md").write_text(
        "---\nname: jan\ntype: user\n---\nbody"
    )
    (md / "archive" / "2024-02" / "user_feb.md").write_text(
        "---\nname: feb\ntype: user\n---\nbody"
    )
    result = CliRunner().invoke(
        cli, ["memory", "archive", "proj", "--month", "2024-01"]
    )
    assert result.exit_code == 0, result.output
    assert "user_jan.md" in result.output
    assert "user_feb.md" not in result.output


def test_archive_json_output(tmp_path: Path, monkeypatch) -> None:
    """``--json`` emits a machine-readable list of entry dicts."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="t", body="b")
    name = pm.list_entries(project_dir)[0]["filename"]
    pm.archive_entry(project_dir, name)

    result = CliRunner().invoke(cli, ["memory", "archive", "proj", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data and data[0]["filename"] == name


def test_archive_uses_single_registered_project(tmp_path: Path, monkeypatch) -> None:
    """Omitting the project arg picks the only registered project."""
    _setup(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["memory", "archive"])
    assert result.exit_code == 0, result.output
    assert "No archived" in result.output
