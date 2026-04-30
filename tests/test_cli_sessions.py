"""Tests for the ``urika sessions`` CLI group (v0.4 Track 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def project_with_sessions(tmp_path: Path, monkeypatch):
    """Build a project + register it + write two sessions."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))

    proj_root = tmp_path / "projects"
    proj_root.mkdir()
    proj = proj_root / "alpha"
    proj.mkdir()
    (proj / "experiments").mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "alpha"\nquestion = "?"\nmode = "exploratory"\n',
        encoding="utf-8",
    )
    (home / "projects.json").write_text(
        json.dumps({"alpha": str(proj)}), encoding="utf-8"
    )

    from urika.core.orchestrator_sessions import (
        OrchestratorSession,
        save_session,
    )

    save_session(
        proj,
        OrchestratorSession(
            session_id="2026-04-30T00-00-00",
            started="2026-04-30T00:00:00Z",
            updated="2026-04-30T00:00:00Z",
            recent_messages=[
                {"role": "user", "content": "hello", "ts": "2026-04-30T00:00:00Z"},
                {
                    "role": "assistant",
                    "content": "hi! what would you like to do?",
                    "ts": "2026-04-30T00:00:01Z",
                },
            ],
            preview="hello",
        ),
    )
    save_session(
        proj,
        OrchestratorSession(
            session_id="2026-04-30T00-05-00",
            started="2026-04-30T00:05:00Z",
            updated="2026-04-30T00:05:00Z",
            recent_messages=[
                {"role": "user", "content": "second session", "ts": "2026-04-30T00:05:00Z"},
            ],
            preview="second session",
        ),
    )
    yield proj


def test_sessions_list_shows_both_sessions(project_with_sessions):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["sessions", "list", "alpha"])
    assert result.exit_code == 0, result.output
    assert "2026-04-30T00-00-00" in result.output
    assert "2026-04-30T00-05-00" in result.output


def test_sessions_list_json_format(project_with_sessions):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["sessions", "list", "alpha", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["project"] == "alpha"
    assert len(data["sessions"]) == 2


def test_sessions_export_md_default(project_with_sessions):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["sessions", "export", "alpha", "2026-04-30T00-00-00"],
    )
    assert result.exit_code == 0, result.output
    assert "# Orchestrator session" in result.output
    assert "hello" in result.output
    assert "hi! what would you like" in result.output


def test_sessions_export_json(project_with_sessions):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["sessions", "export", "alpha", "2026-04-30T00-00-00", "--format", "json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["session_id"] == "2026-04-30T00-00-00"
    assert len(data["recent_messages"]) == 2


def test_sessions_export_to_file(project_with_sessions, tmp_path):
    from urika.cli import cli

    runner = CliRunner()
    out = tmp_path / "session.md"
    result = runner.invoke(
        cli,
        [
            "sessions",
            "export",
            "alpha",
            "2026-04-30T00-00-00",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "# Orchestrator session" in body


def test_sessions_export_unknown_id_errors(project_with_sessions):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(
        cli, ["sessions", "export", "alpha", "does-not-exist"]
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
