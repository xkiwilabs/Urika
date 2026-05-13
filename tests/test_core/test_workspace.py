"""Tests for project workspace creation."""

from pathlib import Path

import pytest

from urika.core.models import ProjectConfig
from urika.core.workspace import (
    _write_toml,
    create_project_workspace,
    load_project_config,
)


class TestCreateProjectWorkspace:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "sleep-study"
        config = ProjectConfig(
            name="sleep-study",
            question="What predicts sleep quality?",
            mode="exploratory",
        )
        create_project_workspace(project_dir, config)

        assert (project_dir / "urika.toml").exists()
        assert (project_dir / "data").is_dir()
        assert (project_dir / "tools").is_dir()
        assert (project_dir / "methods").is_dir()
        assert (project_dir / "knowledge").is_dir()
        assert (project_dir / "experiments").is_dir()
        assert (project_dir / "projectbook").is_dir()

    def test_writes_urika_toml(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test-project"
        config = ProjectConfig(
            name="test-project",
            question="Does X cause Y?",
            mode="confirmatory",
        )
        create_project_workspace(project_dir, config)

        loaded = load_project_config(project_dir)
        assert loaded.name == "test-project"
        assert loaded.mode == "confirmatory"

    def test_creates_projectbook_stubs(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(name="test", question="?", mode="exploratory")
        create_project_workspace(project_dir, config)

        assert (project_dir / "projectbook" / "key-findings.md").exists()
        assert (project_dir / "projectbook" / "results-summary.md").exists()
        assert (project_dir / "projectbook" / "progress-overview.md").exists()

    def test_raises_if_dir_exists(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "exists"
        project_dir.mkdir()
        (project_dir / "urika.toml").write_text("")

        config = ProjectConfig(name="exists", question="?", mode="exploratory")
        with pytest.raises(FileExistsError):
            create_project_workspace(project_dir, config)


class TestLoadProjectConfig:
    def test_load(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "test"
        config = ProjectConfig(
            name="test",
            question="Does X work?",
            mode="pipeline",
            data_paths=["data/input.csv"],
        )
        create_project_workspace(project_dir, config)

        loaded = load_project_config(project_dir)
        assert loaded.name == "test"
        assert loaded.mode == "pipeline"
        assert loaded.data_paths == ["data/input.csv"]

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_project_config(tmp_path / "nope")


class TestWriteTomlInheritanceComment:
    """``_write_toml`` prepends a comment block to project TOMLs whose
    ``[privacy].mode`` is private or hybrid, explaining that per-agent
    models and endpoints inherit from globals.  Runtime behavior is
    unchanged; this is purely documentation for users reading the
    file directly."""

    def test_private_mode_emits_inheritance_comment(self, tmp_path: Path) -> None:
        path = tmp_path / "urika.toml"
        _write_toml(
            path,
            {
                "project": {"name": "p", "mode": "exploratory"},
                "privacy": {"mode": "private"},
            },
        )
        text = path.read_text()
        assert "Privacy mode: private" in text
        assert "settings.toml" in text
        assert "[runtime.modes.private]" in text
        assert "[privacy.endpoints.*]" in text
        # Comment must come before the [project] section.
        assert text.find("Privacy mode") < text.find("[project]")

    def test_hybrid_mode_emits_inheritance_comment(self, tmp_path: Path) -> None:
        path = tmp_path / "urika.toml"
        _write_toml(
            path,
            {
                "project": {"name": "p", "mode": "exploratory"},
                "privacy": {"mode": "hybrid"},
            },
        )
        text = path.read_text()
        assert "Privacy mode: hybrid" in text
        assert "[runtime.modes.hybrid]" in text

    def test_open_mode_no_inheritance_comment(self, tmp_path: Path) -> None:
        path = tmp_path / "urika.toml"
        _write_toml(
            path,
            {
                "project": {"name": "p", "mode": "exploratory"},
                "privacy": {"mode": "open"},
            },
        )
        text = path.read_text()
        # Open mode never inherits a private endpoint, so the comment
        # would be misleading. Skip it.
        assert "Privacy mode" not in text

    def test_no_privacy_block_no_inheritance_comment(self, tmp_path: Path) -> None:
        path = tmp_path / "urika.toml"
        _write_toml(
            path,
            {"project": {"name": "p", "mode": "exploratory"}},
        )
        text = path.read_text()
        assert "Privacy mode" not in text

    def test_inheritance_comment_does_not_break_toml_parser(
        self, tmp_path: Path
    ) -> None:
        """A TOML file with the comment block must still parse cleanly."""
        import tomllib

        path = tmp_path / "urika.toml"
        _write_toml(
            path,
            {
                "project": {"name": "p", "mode": "exploratory"},
                "privacy": {"mode": "private"},
            },
        )
        with open(path, "rb") as f:
            parsed = tomllib.load(f)
        assert parsed["project"]["name"] == "p"
        assert parsed["privacy"]["mode"] == "private"


class TestSpecialCharsRoundTrip:
    """A research question / description pasted with quotes, backslashes,
    or control characters (a Windows ``\\r\\n``, a tab) must produce
    *valid* TOML so the project is loadable. Pre-v0.4.4 the encoder
    only escaped ``\\``, ``"`` and ``\\n`` — a stray ``\\r`` made
    ``urika.toml`` unparseable. (Plausible cause of "the dashboard
    create button doesn't work when I type a real question".)"""

    @pytest.mark.parametrize(
        "question, description",
        [
            ('Does "affect" predict mood over time?', "Has, commas. And periods."),
            ("Windows pasted\r\nmulti-line question", "tab\there too"),
            ("path-like c:\\users\\x\\data", "weird \x01 control char"),
            ("emoji ✓ and accents é à", "ünïcödé"),
        ],
    )
    def test_create_and_reload_with_special_chars(
        self, tmp_path: Path, question: str, description: str
    ) -> None:
        project_dir = tmp_path / "p"
        config = ProjectConfig(
            name="p", question=question, mode="exploratory", description=description
        )
        create_project_workspace(project_dir, config)
        # The file must be valid TOML (this is what broke pre-fix).
        import tomllib

        with open(project_dir / "urika.toml", "rb") as f:
            tomllib.load(f)
        # And it must round-trip.
        loaded = load_project_config(project_dir)
        assert loaded.question == question
        assert loaded.description == description

    def test_toml_basic_string_round_trips(self) -> None:
        import tomllib

        from urika.core.workspace import _toml_basic_string

        for s in ['x"y\\z', "a\r\nb", "t\tt", "\x07", "plain", "é✓", ""]:
            assert tomllib.loads("v = " + _toml_basic_string(s))["v"] == s
