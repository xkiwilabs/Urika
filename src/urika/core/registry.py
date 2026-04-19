"""Central project registry at ~/.urika/projects.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _urika_home() -> Path:
    """Return the Urika home directory, respecting URIKA_HOME env var."""
    env = os.environ.get("URIKA_HOME")
    if env:
        return Path(env)
    return Path.home() / ".urika"


class ProjectRegistry:
    """Manages the central registry of Urika projects."""

    def __init__(self) -> None:
        self._home = _urika_home()
        self._home.mkdir(parents=True, exist_ok=True)
        self._path = self._home / "projects.json"
        self._data = self._load()

    def _load(self) -> dict[str, str]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError) as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Corrupt JSON in %s: %s — starting fresh", self._path, exc
                )
                return {}
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")

    def register(self, name: str, path: Path) -> None:
        """Register a project by name and path."""
        self._data[name] = str(path)
        self._save()

    def get(self, name: str) -> Path | None:
        """Get a project path by name, or None if not found."""
        raw = self._data.get(name)
        return Path(raw) if raw else None

    def remove(self, name: str) -> None:
        """Remove a project from the registry."""
        self._data.pop(name, None)
        self._save()

    def list_all(self) -> dict[str, Path]:
        """Return all registered projects as {name: path}."""
        return {k: Path(v) for k, v in self._data.items()}
