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
            f"[project]\n"
            f'name = "{name}"\n'
            f'question = "q for {name}"\n'
            f'mode = "exploratory"\n'
            f'description = ""\n'
            f"\n"
            f"[preferences]\n"
            f'audience = "expert"\n'
        )

    # Force the ProjectRegistry to read from a tmp file
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(
        json.dumps(
            {
                "alpha": str(tmp_path / "alpha"),
                "beta": str(tmp_path / "beta"),
            }
        )
    )

    app = create_app(project_root=tmp_path)
    return TestClient(app)


@pytest.fixture
def audit_client(tmp_path: Path, monkeypatch) -> TestClient:
    """One project ('alpha') with an experiment + run + method + knowledge.

    Shared by the visual-audit and accessibility test modules. (The
    visual-audit module also defines a local copy; the local one wins
    there, so this conftest version serves the accessibility module.)
    """
    proj = tmp_path / "alpha"
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "q"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
    )

    exp_id = "exp-001"
    exp_dir = proj / "experiments" / exp_id
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "name": "baseline",
                "hypothesis": "linear models will fit",
                "status": "completed",
                "created_at": "2026-04-25T00:00:00Z",
            }
        )
    )
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "status": "completed",
                "runs": [
                    {
                        "run_id": "run-001",
                        "method": "ols",
                        "params": {},
                        "metrics": {"r2": 0.5},
                        "observation": "obs",
                        "timestamp": "2026-04-25T00:00:00Z",
                    }
                ],
            }
        )
    )
    (proj / "methods.json").write_text(
        json.dumps(
            {
                "methods": [
                    {
                        "name": "ols",
                        "description": "linear",
                        "script": "ols.py",
                        "experiment": exp_id,
                        "turn": 1,
                        "metrics": {"r2": 0.5},
                        "status": "active",
                    },
                ]
            }
        )
    )
    knowledge_dir = proj / "knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": "k-001",
                        "source": "/tmp/paper.pdf",
                        "source_type": "pdf",
                        "title": "A paper",
                        "content": "body",
                        "tags": [],
                        "added_at": "2026-04-25T00:00:00Z",
                    }
                ]
            }
        )
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))

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
