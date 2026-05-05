"""Tests for ``urika new --overwrite`` flag — v0.4.2 C4 regression suite.

Pre-v0.4.2 ``urika new --json`` silently ``shutil.rmtree``'d any
existing project of the same name with no flag and no confirmation —
a scripted-create user could lose a real project by accident.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli


class TestJsonOverwriteRefusal:
    def test_existing_project_without_flag_is_refused(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
        monkeypatch.setenv("URIKA_PROJECTS_DIR", str(tmp_path / "projects"))
        monkeypatch.setenv("URIKA_NO_BUILDER_AGENT", "1")

        # Pre-seed an existing project of the same name.
        project_dir = tmp_path / "projects" / "myproj"
        project_dir.mkdir(parents=True)
        (project_dir / "urika.toml").write_text(
            '[project]\nname = "myproj"\nquestion = "old"\n'
        )
        canary = project_dir / "canary-do-not-lose.txt"
        canary.write_text("user data")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "new",
                "myproj",
                "-q", "new question",
                "-m", "exploratory",
                "--json",
            ],
        )

        # Must refuse with non-zero exit and surface a useful message.
        assert result.exit_code != 0
        # Output is JSON error per cli_helpers.output_json_error contract.
        try:
            data = json.loads(result.output)
            assert "already exists" in data.get("error", "").lower()
            assert "--overwrite" in data.get("error", "")
        except json.JSONDecodeError:
            # Fallback: still must mention overwrite somewhere.
            assert "overwrite" in result.output.lower()

        # The original project (and its data) must be untouched.
        assert canary.exists(), "Pre-v0.4.2 silently deleted the existing project!"
        assert canary.read_text() == "user data"

    def test_overwrite_flag_replaces_existing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
        monkeypatch.setenv("URIKA_PROJECTS_DIR", str(tmp_path / "projects"))
        monkeypatch.setenv("URIKA_NO_BUILDER_AGENT", "1")

        # Pre-seed an existing project.
        project_dir = tmp_path / "projects" / "myproj"
        project_dir.mkdir(parents=True)
        (project_dir / "urika.toml").write_text(
            '[project]\nname = "myproj"\nquestion = "old"\n'
        )
        (project_dir / "stale-marker.txt").write_text("from old project")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "new",
                "myproj",
                "-q", "new question",
                "-m", "exploratory",
                "--json",
                "--overwrite",
            ],
        )

        # Should succeed and the stale marker should be gone.
        assert result.exit_code == 0, result.output
        assert not (project_dir / "stale-marker.txt").exists()
        # New urika.toml has the new question.
        assert (project_dir / "urika.toml").exists()
        assert "new question" in (project_dir / "urika.toml").read_text()
