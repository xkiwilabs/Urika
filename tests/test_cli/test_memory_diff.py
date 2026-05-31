"""Tests for ``urika memory diff <from> <to>`` (v0.5.0 Task 3.2).

Shows memory entries added / archived / trashed between two timestamps,
accepting either ISO 8601 or simple relative forms (``now``,
``yesterday``, ``Nh ago``, ``Nd ago``, ``Nw ago``).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def test_diff_relative_timestamps(tmp_path: Path, monkeypatch) -> None:
    """A just-created entry should appear under ``added`` for a
    ``1h ago`` / ``now`` window."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="recent", body="b")

    result = CliRunner().invoke(cli, ["memory", "diff", "proj", "1h ago", "now"])
    assert result.exit_code == 0, result.output
    assert "added" in result.output
    # The saved filename should appear, e.g. user_recent.md.
    assert "user_recent.md" in result.output


def test_diff_empty_window(tmp_path: Path, monkeypatch) -> None:
    """Window with no events prints 'No changes'."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="recent", body="b")

    result = CliRunner().invoke(cli, ["memory", "diff", "proj", "2w ago", "1w ago"])
    assert result.exit_code == 0, result.output
    assert "No changes" in result.output


def test_diff_bad_timestamp(tmp_path: Path, monkeypatch) -> None:
    """Unparseable timestamps exit 1 with a helpful message."""
    _setup(tmp_path, monkeypatch)
    result = CliRunner().invoke(cli, ["memory", "diff", "proj", "garbage", "now"])
    assert result.exit_code == 1
    combined = result.output + (
        result.stderr if result.stderr_bytes is not None else ""
    )
    assert "Cannot parse" in combined


def test_diff_iso_timestamps(tmp_path: Path, monkeypatch) -> None:
    """ISO 8601 timestamps work too."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="x", body="b")

    f = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    t = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result = CliRunner().invoke(cli, ["memory", "diff", "proj", f, t])
    assert result.exit_code == 0, result.output
    assert "added" in result.output


def test_diff_json_output(tmp_path: Path, monkeypatch) -> None:
    """``--json`` emits the raw ``diff_between`` payload."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="x", body="b")

    result = CliRunner().invoke(
        cli, ["memory", "diff", "proj", "1h ago", "now", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "added" in data and "archived" in data and "trashed" in data
    assert any(e["filename"] == "user_x.md" for e in data["added"])


def test_diff_yesterday_and_now(tmp_path: Path, monkeypatch) -> None:
    """The ``yesterday`` keyword is accepted."""
    project_dir = _setup(tmp_path, monkeypatch)
    pm.save_entry(project_dir, mem_type="user", description="z", body="b")
    result = CliRunner().invoke(cli, ["memory", "diff", "proj", "yesterday", "now"])
    assert result.exit_code == 0, result.output
    assert "added" in result.output
