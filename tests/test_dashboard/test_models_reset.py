"""Tests for the dashboard's "Reset to recommended defaults" endpoints
on the Models tab — both global (`POST /api/settings/models/reset`)
and project-scoped (`POST /api/projects/<n>/settings/models/reset`).

Mirrors the CLI's `urika config --reset-models` flag. Both surfaces
delegate to the same helper in `urika.core.recommended_models`.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch) -> TestClient:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    app = create_app(project_root=tmp_path)
    return TestClient(app)


def test_global_reset_opus_open_writes_split(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    (home / "settings.toml").write_text(
        """[runtime.modes.open]
model = "claude-opus-4-6"
"""
    )
    client = TestClient(create_app(project_root=tmp_path))

    r = client.post("/api/settings/models/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["split_applied_to"] == ["open"]

    s = tomllib.loads((home / "settings.toml").read_text())
    open_mode = s["runtime"]["modes"]["open"]
    assert open_mode["model"] == "claude-opus-4-6"
    assert open_mode["models"]["task_agent"]["model"] == "claude-sonnet-4-5"
    assert open_mode["models"]["planning_agent"]["model"] == "claude-opus-4-6"


def test_global_reset_sonnet_clears_overrides(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text("{}")
    (home / "settings.toml").write_text(
        """[runtime.modes.open]
model = "claude-sonnet-4-5"

[runtime.modes.open.models.task_agent]
model = "claude-haiku-4-5"
endpoint = "open"
"""
    )
    client = TestClient(create_app(project_root=tmp_path))

    r = client.post("/api/settings/models/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["split_applied_to"] == []

    s = tomllib.loads((home / "settings.toml").read_text())
    assert s["runtime"]["modes"]["open"]["model"] == "claude-sonnet-4-5"
    assert "models" not in s["runtime"]["modes"]["open"]


def test_project_reset_opus_writes_split(tmp_path: Path, monkeypatch):
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        """[project]
name = "alpha"
question = "?"
mode = "exploratory"

[privacy]
mode = "open"

[runtime]
model = "claude-opus-4-6"

[runtime.models.task_agent]
model = "claude-opus-4-6"
endpoint = "open"
"""
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.post("/api/projects/alpha/settings/models/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["split_applied"] is True
    assert body["default_model"] == "claude-opus-4-6"

    s = tomllib.loads((proj / "urika.toml").read_text())
    assert s["runtime"]["model"] == "claude-opus-4-6"
    assert s["runtime"]["models"]["task_agent"]["model"] == "claude-sonnet-4-5"
    assert s["runtime"]["models"]["planning_agent"]["model"] == "claude-opus-4-6"


def test_project_reset_hybrid_preserves_private_pins(tmp_path: Path, monkeypatch):
    proj = tmp_path / "alpha"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        """[project]
name = "alpha"
question = "?"
mode = "exploratory"

[privacy]
mode = "hybrid"

[runtime]
model = "claude-opus-4-6"

[runtime.models.data_agent]
model = "qwen3:14b"
endpoint = "private"

[runtime.models.tool_builder]
model = "qwen3:14b"
endpoint = "private"
"""
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(proj)}))
    client = TestClient(create_app(project_root=tmp_path))

    r = client.post("/api/projects/alpha/settings/models/reset")
    assert r.status_code == 200

    s = tomllib.loads((proj / "urika.toml").read_text())
    models = s["runtime"]["models"]
    # Reasoning agents pinned to project default.
    assert models["planning_agent"]["model"] == "claude-opus-4-6"
    # Cloud execution agents on Sonnet.
    assert models["task_agent"]["model"] == "claude-sonnet-4-5"
    # Private pins preserved across the rebuild.
    assert models["data_agent"]["model"] == "qwen3:14b"
    assert models["data_agent"]["endpoint"] == "private"
    assert models["tool_builder"]["model"] == "qwen3:14b"
    assert models["tool_builder"]["endpoint"] == "private"


def test_project_reset_unknown_project_404(settings_client: TestClient):
    r = settings_client.post("/api/projects/nonexistent/settings/models/reset")
    assert r.status_code == 404
