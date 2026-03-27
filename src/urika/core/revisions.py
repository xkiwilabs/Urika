"""Versioned project config revisions with timestamps."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _revisions_path(project_dir: Path) -> Path:
    return project_dir / "revisions.json"


def load_revisions(project_dir: Path) -> list[dict[str, Any]]:
    """Load all project revisions."""
    path = _revisions_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("revisions", [])
    except Exception:
        return []


def record_revision(
    project_dir: Path,
    *,
    field: str,
    old_value: str,
    new_value: str,
    reason: str = "",
) -> dict[str, Any]:
    """Record a revision to a project config field.

    Returns the revision entry.
    """
    revisions = load_revisions(project_dir)
    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
        "revision": len(revisions) + 1,
    }
    revisions.append(entry)
    _revisions_path(project_dir).write_text(
        json.dumps({"revisions": revisions}, indent=2) + "\n"
    )
    return entry


def update_project_field(
    project_dir: Path,
    *,
    field: str,
    new_value: str,
    reason: str = "",
) -> dict[str, Any]:
    """Update a project config field and record the revision.

    Supported fields: 'description', 'question', 'mode'.
    Updates urika.toml and records the change in revisions.json.

    Returns the revision entry.
    """
    import tomllib

    from urika.core.workspace import _write_toml

    valid_fields = {"description", "question", "mode"}
    if field not in valid_fields:
        msg = f"Cannot update field '{field}'. Valid: {valid_fields}"
        raise ValueError(msg)

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        msg = f"No urika.toml at {project_dir}"
        raise FileNotFoundError(msg)

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    old_value = data.get("project", {}).get(field, "")
    data.setdefault("project", {})[field] = new_value

    # Preserve non-project sections (privacy, runtime, etc.)
    # by reading raw content and only updating the project section
    _write_toml(toml_path, data)

    return record_revision(
        project_dir,
        field=field,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )
