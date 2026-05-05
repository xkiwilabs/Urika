from pathlib import Path
import json
import time
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 2.0,
    poll: float = 0.05,
    description: str = "predicate",
) -> bool:
    """Poll *predicate* until it returns truthy or *timeout* elapses.

    v0.4.2 M14 — replaces ``time.sleep(0.5)`` / ``time.sleep(0.6)``
    blocks scattered through SSE-stream tests. Sleeps were timing-
    coupled (would flake on slower CI boxes if poll cadence shifts)
    and added ~1.2s of wall-clock per test. ``wait_until`` returns as
    soon as the condition is true, then ``raise TimeoutError`` if it
    never becomes true within the budget.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(poll)
    raise TimeoutError(f"{description} did not become true within {timeout}s")


@pytest.fixture
def client_with_projects(tmp_path: Path, monkeypatch) -> TestClient:
    """A dashboard whose registry is forced to point at tmp projects."""
    # Fabricate two projects on disk
    for name in ("alpha", "beta"):
        proj = tmp_path / name
        proj.mkdir()
        (proj / "urika.toml").write_text(
            f'[project]\n'
            f'name = "{name}"\n'
            f'question = "q for {name}"\n'
            f'mode = "exploratory"\n'
            f'description = ""\n'
            f'\n'
            f'[preferences]\n'
            f'audience = "expert"\n'
        )

    # Force the ProjectRegistry to read from a tmp file
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({
        "alpha": str(tmp_path / "alpha"),
        "beta": str(tmp_path / "beta"),
    }))

    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    # Empty registry — settings page doesn't need projects.
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    return TestClient(app)
