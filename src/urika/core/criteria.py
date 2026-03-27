"""Versioned project criteria — evolves during experiments."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from urika.core.filelock import locked_json_update

logger = logging.getLogger(__name__)


def _criteria_path(project_dir: Path) -> Path:
    return project_dir / "criteria.json"


@dataclass
class CriteriaVersion:
    """A single version of the project criteria."""

    version: int
    set_by: str
    turn: int
    rationale: str
    criteria: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "set_by": self.set_by,
            "turn": self.turn,
            "rationale": self.rationale,
            "criteria": self.criteria,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CriteriaVersion:
        return cls(
            version=d["version"],
            set_by=d["set_by"],
            turn=d.get("turn", 0),
            rationale=d.get("rationale", ""),
            criteria=d.get("criteria", {}),
        )


def load_criteria(project_dir: Path) -> CriteriaVersion | None:
    """Load the latest criteria version, or None if no criteria file exists."""
    path = _criteria_path(project_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt JSON in %s: %s", path, exc)
        return None
    versions = data.get("versions", [])
    if not versions:
        return None
    return CriteriaVersion.from_dict(versions[-1])


def load_criteria_history(project_dir: Path) -> list[CriteriaVersion]:
    """Load all criteria versions."""
    path = _criteria_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Corrupt JSON in %s: %s", path, exc)
        return []
    return [CriteriaVersion.from_dict(v) for v in data.get("versions", [])]


def append_criteria(
    project_dir: Path,
    criteria: dict[str, Any],
    *,
    set_by: str,
    turn: int,
    rationale: str,
) -> CriteriaVersion:
    """Append a new criteria version. Creates the file if it doesn't exist."""
    path = _criteria_path(project_dir)
    with locked_json_update(path):
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Corrupt JSON in %s: %s", path, exc)
                data = {"versions": []}
        else:
            data = {"versions": []}

        versions = data.get("versions", [])
        next_version = len(versions) + 1

        entry = CriteriaVersion(
            version=next_version,
            set_by=set_by,
            turn=turn,
            rationale=rationale,
            criteria=criteria,
        )
        versions.append(entry.to_dict())
        data["versions"] = versions
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return entry
