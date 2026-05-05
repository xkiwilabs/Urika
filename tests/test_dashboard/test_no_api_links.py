"""No browser-rendered page should expose /api/* as a clickable href.

Programmatic /api/* endpoints are agent/script targets — they should
only be reached via HTMX (hx-post/hx-put/hx-get), fetch(), or
EventSource(), never via a plain ``<a href="/api/...">`` link.
"""

from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _make_project_with_runs(root: Path, name: str, exp_id: str, n_runs: int) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "urika.toml").write_text(
        f'[project]\nname = "{name}"\nquestion = "q for {name}"\n'
        f'mode = "exploratory"\ndescription = ""\n\n'
        f'[preferences]\naudience = "expert"\n'
    )
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
    runs = [
        {
            "run_id": f"run-{i + 1:03d}",
            "method": "ols",
            "params": {},
            "metrics": {"r2": 0.5 + i * 0.01},
            "observation": f"observation for run {i + 1}",
            "timestamp": f"2026-04-25T0{i}:00:00Z",
        }
        for i in range(n_runs)
    ]
    (exp_dir / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": exp_id,
                "status": "completed",
                "runs": runs,
            }
        )
    )
    return proj


@pytest.fixture
def client_with_runs(tmp_path: Path, monkeypatch) -> TestClient:
    _make_project_with_runs(tmp_path, "alpha", "exp-001", 3)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(tmp_path / "alpha")}))
    app = create_app(project_root=tmp_path)
    return TestClient(app)


PAGES_TO_AUDIT = [
    "/projects",
    "/projects/alpha",
    "/projects/alpha/experiments",
    "/projects/alpha/experiments/exp-001",
    "/projects/alpha/experiments/exp-001/log",
    "/projects/alpha/methods",
    "/projects/alpha/knowledge",
    "/projects/alpha/run",
    "/projects/alpha/settings",
    "/settings",
]


# v0.4.2 M20: pre-fix the parametrize loop swallowed 404 responses
# via ``pytest.skip(f"{path} 404 in this fixture")``. That meant a real
# regression — a future commit accidentally breaking one of these
# pages — would silently pass instead of failing. The skip is now
# gone: every audit-listed path must respond 200, otherwise the test
# fails. If a future contributor adds a path that genuinely needs a
# different fixture state, they should split it into its own
# parametrize set rather than reintroducing a generic skip.


@pytest.mark.parametrize("path", PAGES_TO_AUDIT)
def test_no_api_href_in_rendered_page(client_with_runs, path):
    r = client_with_runs.get(path)
    assert r.status_code == 200, (
        f"{path} returned {r.status_code} — pre-v0.4.2 this would have "
        f"silently skipped, now it fails so the regression surfaces."
    )
    # Find all <a href="..."> values and assert none start with /api/
    import re

    for m in re.finditer(r'<a[^>]*\bhref="(/api/[^"]+)"', r.text):
        pytest.fail(f"Page {path} exposes /api/* link: {m.group(1)}")
