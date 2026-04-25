"""Tests for urika.core.revisions."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from urika.core.revisions import update_project_field
from urika.core.workspace import _write_toml


def _make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "demo"
    proj.mkdir()
    _write_toml(
        proj / "urika.toml",
        {
            "project": {
                "name": "demo",
                "question": "q",
                "mode": "exploratory",
                "description": "",
            },
            "preferences": {"audience": "expert"},
        },
    )
    return proj


def test_update_project_field_question(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    update_project_field(proj, field="question", new_value="new question")

    data = tomllib.loads((proj / "urika.toml").read_text())
    assert data["project"]["question"] == "new question"

    revisions = json.loads((proj / "revisions.json").read_text())["revisions"]
    assert revisions[-1]["field"] == "question"
    assert revisions[-1]["new_value"] == "new question"
    assert revisions[-1]["old_value"] == "q"


def test_update_project_field_audience(tmp_path: Path) -> None:
    """audience writes to [preferences].audience and records a revision."""
    proj = _make_project(tmp_path)
    update_project_field(proj, field="audience", new_value="novice")

    data = tomllib.loads((proj / "urika.toml").read_text())
    assert data["preferences"]["audience"] == "novice"
    # [project] section is untouched
    assert data["project"]["question"] == "q"

    revisions = json.loads((proj / "revisions.json").read_text())["revisions"]
    assert revisions[-1]["field"] == "audience"
    assert revisions[-1]["new_value"] == "novice"
    assert revisions[-1]["old_value"] == "expert"


def test_update_project_field_rejects_unknown_field(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    with pytest.raises(ValueError, match="Cannot update field"):
        update_project_field(proj, field="bogus", new_value="x")


def test_update_project_field_missing_toml(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        update_project_field(empty, field="question", new_value="x")
