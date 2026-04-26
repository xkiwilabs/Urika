"""Tests for the persistent running-ops banner across project pages."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from urika.dashboard.app import create_app


def _write_lock(path: Path, pid: int | str) -> None:
    """Write a PID lock file at ``path``, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def _write_project(root: Path, name: str = "alpha") -> Path:
    proj = root / name
    proj.mkdir(parents=True, exist_ok=True)
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
    return proj


@pytest.fixture
def banner_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    """A dashboard whose registry points at a single tmp project ``alpha``.

    Returns ``(client, project_path)`` so tests can drop lock files into
    the project on demand.
    """
    project = _write_project(tmp_path, "alpha")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    (home / "projects.json").write_text(json.dumps({"alpha": str(project)}))
    app = create_app(project_root=tmp_path)
    return TestClient(app), project


def _banner_chip_hrefs(body: str) -> list[str]:
    """Extract href attributes of every ``active-op-chip`` anchor."""
    return re.findall(r'<a[^>]*class="active-op-chip"[^>]*href="([^"]+)"', body)


def test_banner_absent_when_no_active_ops(banner_client) -> None:
    client, _ = banner_client
    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert "active-ops-banner" not in body
    assert "Running:" not in body


def test_banner_visible_with_one_op_on_project_home(banner_client) -> None:
    client, project = banner_client
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())

    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    assert "active-ops-banner" in body
    assert "Running:" in body
    hrefs = _banner_chip_hrefs(body)
    assert "/projects/alpha/summarize/log" in hrefs


def test_banner_visible_on_other_project_pages(banner_client) -> None:
    client, project = banner_client
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())

    for path in (
        "/projects/alpha/experiments",
        "/projects/alpha/methods",
        "/projects/alpha/tools",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.text
        assert "active-ops-banner" in body, f"banner missing on {path}"
        hrefs = _banner_chip_hrefs(body)
        assert "/projects/alpha/summarize/log" in hrefs, (
            f"summarize chip missing on {path}"
        )


def test_banner_lists_multiple_concurrent_ops(banner_client) -> None:
    client, project = banner_client
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())
    _write_lock(project / "experiments" / "exp-001" / ".lock", os.getpid())

    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    hrefs = _banner_chip_hrefs(body)
    assert "/projects/alpha/summarize/log" in hrefs
    assert "/projects/alpha/experiments/exp-001/log" in hrefs
    # The run chip should carry the experiment id text.
    assert "exp-001" in body
    # Verb appears in chip text.
    assert "summarize" in body
    assert "run" in body


def test_banner_suppresses_self_link_on_log_page(banner_client) -> None:
    client, project = banner_client
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())

    r = client.get("/projects/alpha/summarize/log")
    assert r.status_code == 200
    body = r.text
    # The chip pointing back to THIS very page must not be rendered.
    hrefs = _banner_chip_hrefs(body)
    assert "/projects/alpha/summarize/log" not in hrefs


def test_banner_chip_includes_experiment_id_for_per_experiment_ops(
    banner_client,
) -> None:
    client, project = banner_client
    _write_lock(project / "experiments" / "exp-042" / ".evaluate.lock", os.getpid())

    r = client.get("/projects/alpha")
    assert r.status_code == 200
    body = r.text
    hrefs = _banner_chip_hrefs(body)
    assert "/projects/alpha/experiments/exp-042/log?type=evaluate" in hrefs
    # The chip text mentions both the verb and the experiment id.
    assert "evaluate" in body
    assert "exp-042" in body


def test_banner_absent_on_global_pages(banner_client) -> None:
    client, project = banner_client
    # Even with a live op, global (non-project) pages must not render
    # the banner — they have no project context.
    _write_lock(project / "projectbook" / ".summarize.lock", os.getpid())

    for path in ("/projects", "/settings"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "active-ops-banner" not in r.text, (
            f"banner unexpectedly present on {path}"
        )
