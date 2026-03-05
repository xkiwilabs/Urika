"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with minimal structure."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def tmp_urika_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary ~/.urika directory and patch URIKA_HOME."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(urika_home))
    return urika_home
