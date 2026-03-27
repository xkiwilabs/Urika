"""Project virtual environment management."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def create_project_venv(project_dir: Path) -> Path:
    """Create a project-specific venv with --system-site-packages.

    Inherits packages from the global environment so only
    project-specific additions need to be installed.
    Returns the venv path.
    """
    venv_path = project_dir / ".venv"
    if venv_path.exists():
        return venv_path
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_path), "--system-site-packages"],
        check=True,
    )
    return venv_path


def get_venv_env(project_dir: Path) -> dict[str, str] | None:
    """Get environment dict for a project's venv, or None if no venv.

    Reads urika.toml to check if venv is enabled. If so, returns
    a dict with PATH and VIRTUAL_ENV set to use the project venv.
    """
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return None
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        if not data.get("environment", {}).get("venv", False):
            return None
    except Exception:
        return None

    venv_path = project_dir / ".venv"
    if not venv_path.exists():
        return None

    venv_bin = venv_path / ("Scripts" if sys.platform == "win32" else "bin")
    env = dict(os.environ)
    env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(venv_path)
    # Remove PYTHONHOME if set — interferes with venvs
    env.pop("PYTHONHOME", None)
    return env


def is_venv_enabled(project_dir: Path) -> bool:
    """Check if a project has venv enabled in urika.toml."""
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return False
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return bool(data.get("environment", {}).get("venv", False))
    except Exception:
        return False
