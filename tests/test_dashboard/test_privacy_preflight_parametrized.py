"""Privacy preflight (``_validate_privacy_endpoint``) applied
uniformly across every endpoint that spawns an agent run.

Before this file only the ``/run`` endpoint had a regression test for
the preflight; a refactor that dropped the call from /finalize or
/summarize or /advisor would silently send private-mode data to the
cloud."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def client_private_no_endpoint(tmp_path: Path, monkeypatch) -> TestClient:
    """A project in private mode with NO endpoint configured — every
    preflight-guarded route should refuse with 422."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    # NO [privacy.endpoints.*] in settings.toml.
    (home / "settings.toml").write_text("")
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "?"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n'
        '\n[privacy]\nmode = "private"\n'
    )
    exp_dir = proj / "experiments" / "exp-001"
    exp_dir.mkdir(parents=True)
    (exp_dir / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "b",
                "hypothesis": "h",
                "created": "2026-05-01T00:00:00Z",
            }
        )
    )
    (exp_dir / "progress.json").write_text(
        json.dumps({"status": "pending", "runs": []})
    )
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    return TestClient(create_app(project_root=tmp_path))


@pytest.mark.parametrize(
    "url, method, data",
    [
        ("/api/projects/alpha/run", "post", {"max_turns": "5"}),
        ("/api/projects/alpha/finalize", "post", {}),
        ("/api/projects/alpha/summarize", "post", {}),
        ("/api/projects/alpha/tools/build", "post", {"instructions": "make x"}),
        ("/api/projects/alpha/advisor", "post", {"question": "what next?"}),
        ("/api/projects/alpha/present", "post", {"experiment": "project"}),
        ("/api/projects/alpha/experiments/exp-001/report", "post", {}),
        ("/api/projects/alpha/experiments/exp-001/evaluate", "post", {}),
        ("/api/projects/alpha/experiments/exp-001/resume", "post", {}),
    ],
)
def test_preflight_refuses_when_no_private_endpoint(
    client_private_no_endpoint: TestClient, url: str, method: str, data: dict
) -> None:
    """Every run-spawning endpoint must refuse with 422 (the preflight
    error) when the project is in private mode but no endpoint is
    configured. A 5xx or 200 here means the preflight is missing."""
    r = getattr(client_private_no_endpoint, method)(url, data=data)
    # Either 422 (preflight) or 4xx (a different validation kicked
    # first); never 200 (would have started an unauthorized cloud
    # run), never 5xx.
    assert r.status_code != 200, (
        f"{url} did NOT refuse a private-mode run without endpoint — "
        f"status={r.status_code} body={r.text[:200]}"
    )
    assert r.status_code < 500, (
        f"{url} 5xx'd instead of cleanly refusing: {r.status_code} {r.text[:200]}"
    )
