from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


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
