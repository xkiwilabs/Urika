"""Tests for remaining CLI commands: usage, config, update, dashboard, venv."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from urika.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def urika_env(tmp_path: Path) -> dict[str, str]:
    """Environment with URIKA_HOME and URIKA_PROJECTS_DIR set."""
    urika_home = tmp_path / ".urika"
    urika_home.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return {
        "URIKA_HOME": str(urika_home),
        "URIKA_PROJECTS_DIR": str(projects_dir),
    }


def _create_project(
    runner: CliRunner, urika_env: dict[str, str], name: str = "test-proj"
) -> None:
    """Helper to create a project for tests."""
    # Prompts: privacy(1=open), data_path(empty), description(empty),
    #          web_search(n), venv(n), run(5=skip)
    result = runner.invoke(
        cli,
        ["new", name, "-q", "Does X?", "-m", "exploratory"],
        env=urika_env,
        input="1\n\n\nn\nn\n5\n",
    )
    assert result.exit_code == 0, result.output


def _project_dir(urika_env: dict[str, str], name: str = "test-proj") -> Path:
    """Return the project directory path."""
    return Path(urika_env["URIKA_PROJECTS_DIR"]) / name


def _seed_usage(project_dir: Path) -> None:
    """Seed a project with usage data."""
    from urika.core.usage import record_session

    record_session(
        project_dir,
        started="2026-01-01T00:00:00Z",
        ended="2026-01-01T00:01:00Z",
        duration_ms=60000,
        tokens_in=1000,
        tokens_out=500,
        cost_usd=0.05,
        agent_calls=3,
        experiments_run=1,
    )


# ── Usage command ──────────────────────────────────────────────


class TestUsageCommand:
    def test_no_usage_data(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(cli, ["usage", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        # No sessions recorded, so totals should show 0
        assert "0 sessions" in result.output

    def test_no_usage_data_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli, ["usage", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "session" in data
        assert "total" in data
        assert data["session"] == {}
        assert data["total"]["sessions"] == 0

    def test_with_seeded_usage(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        _seed_usage(_project_dir(urika_env))
        result = runner.invoke(cli, ["usage", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "1 sessions" in result.output or "1 session" in result.output

    def test_with_seeded_usage_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        _seed_usage(_project_dir(urika_env))
        result = runner.invoke(
            cli, ["usage", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["session"]["tokens_in"] == 1000
        assert data["session"]["tokens_out"] == 500
        assert data["session"]["cost_usd"] == 0.05
        assert data["session"]["agent_calls"] == 3
        assert data["total"]["sessions"] == 1
        assert data["total"]["total_tokens_in"] == 1000
        assert data["total"]["total_tokens_out"] == 500
        assert data["total"]["total_cost_usd"] == 0.05

    def test_all_projects_mode(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env, "proj-a")
        _seed_usage(_project_dir(urika_env, "proj-a"))
        result = runner.invoke(cli, ["usage"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "proj-a" in result.output

    def test_all_projects_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env, "proj-a")
        _seed_usage(_project_dir(urika_env, "proj-a"))
        result = runner.invoke(cli, ["usage", "--json"], env=urika_env)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "projects" in data
        assert "proj-a" in data["projects"]
        assert data["projects"]["proj-a"]["sessions"] == 1

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["usage", "no-such-project"], env=urika_env)
        assert result.exit_code != 0

    def test_multiple_sessions(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        pdir = _project_dir(urika_env)
        _seed_usage(pdir)
        # Seed a second session
        from urika.core.usage import record_session

        record_session(
            pdir,
            started="2026-01-02T00:00:00Z",
            ended="2026-01-02T00:02:00Z",
            duration_ms=120000,
            tokens_in=2000,
            tokens_out=1000,
            cost_usd=0.10,
            agent_calls=5,
            experiments_run=2,
        )
        result = runner.invoke(
            cli, ["usage", "test-proj", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["total"]["sessions"] == 2
        assert data["total"]["total_tokens_in"] == 3000
        assert data["total"]["total_cost_usd"] == 0.15


# ── Config command ─────────────────────────────────────────────


class TestConfigCommand:
    def test_show_project_config(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli, ["config", "test-proj", "--show"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "test-proj" in result.output

    def test_show_project_config_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli, ["config", "test-proj", "--show", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, dict)
        assert "project" in data
        assert data["project"]["name"] == "test-proj"

    def test_show_global_config_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["config", "--show", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["config", "no-such-project", "--show"], env=urika_env
        )
        assert result.exit_code != 0


class TestConfigPrivateEndpointRequired:
    """`urika config` must reject a blank private-endpoint URL.

    The hard-fail at runtime (Commit 1) means a blank URL would crash
    the project's first agent run; we may as well catch it in the
    config wizard where the user can fix it on the spot. The wizard
    raises UserCancelled (caught in config_command) when the URL is
    empty.
    """

    def test_blank_private_endpoint_url_aborts_wizard(
        self, urika_env: dict[str, str], monkeypatch
    ) -> None:
        """Custom server URL (free-text) returning empty must abort the
        wizard with UserCancelled rather than save mode=private with
        no endpoint URL."""
        import os

        from urika.cli.config import _config_interactive
        from urika.cli_helpers import UserCancelled

        # Apply env so settings.toml lands in tmp.
        for k, v in urika_env.items():
            monkeypatch.setenv(k, v)

        # Mode picker → "private". Endpoint type picker → "Custom server URL".
        # Numbered prompts are answered by the displayed string so we map
        # the call sequence to the right choice text.
        numbered_calls = iter([
            "private — all agents use local/server models (nothing leaves your network)",
            "Custom server URL",
        ])

        def fake_numbered(prompt, options, *, default=1, **_):
            return next(numbered_calls)

        # interactive_prompt is called once for the URL after the type
        # picker resolved to "Custom server URL". required=True would
        # normally re-prompt, but here we simulate the user pressing
        # Ctrl+C — the helper raises UserCancelled, which the wizard
        # propagates out.
        def fake_prompt(message, *, default="", required=False, **_):
            if "Server URL" in message:
                raise UserCancelled()
            return default

        monkeypatch.setattr(
            "urika.cli_helpers.interactive_numbered", fake_numbered
        )
        monkeypatch.setattr(
            "urika.cli_helpers.interactive_prompt", fake_prompt
        )

        with pytest.raises(UserCancelled):
            _config_interactive(
                session={"privacy": {}},
                current_mode="open",
                is_project=False,
                project_path=None,
            )

    def test_required_flag_set_on_url_prompts(self) -> None:
        """The URL prompts in the private + hybrid branches must call
        interactive_prompt with required=True. Source-level check —
        cheaper than spinning up the wizard."""
        import inspect

        from urika.cli import config as config_module

        src = inspect.getsource(config_module._config_interactive)
        # Both vLLM and Custom branches must pass required=True now —
        # the previous code did not.
        assert src.count("required=True") >= 2

    def test_blank_url_after_required_loop_raises_user_cancelled(
        self, urika_env: dict[str, str], monkeypatch
    ) -> None:
        """Defensive check: if interactive_prompt somehow returns an
        empty string (EOF on piped stdin with no default), the wizard
        must still cancel rather than save an empty base_url."""
        from urika.cli.config import _config_interactive
        from urika.cli_helpers import UserCancelled

        for k, v in urika_env.items():
            monkeypatch.setenv(k, v)

        numbered_calls = iter([
            "private — all agents use local/server models (nothing leaves your network)",
            "Custom server URL",
        ])

        def fake_numbered(prompt, options, *, default=1, **_):
            return next(numbered_calls)

        def fake_prompt(message, *, default="", required=False, **_):
            # Simulate the EOF/piped-stdin path that returns default
            # without re-prompting — default is empty here.
            return ""

        monkeypatch.setattr(
            "urika.cli_helpers.interactive_numbered", fake_numbered
        )
        monkeypatch.setattr(
            "urika.cli_helpers.interactive_prompt", fake_prompt
        )

        with pytest.raises(UserCancelled):
            _config_interactive(
                session={"privacy": {}},
                current_mode="open",
                is_project=False,
                project_path=None,
            )


# ── Update command ─────────────────────────────────────────────


class TestUpdateCommand:
    def test_update_question(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "Does Y predict Z?",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["field"] == "question"
        assert data["new_value"] == "Does Y predict Z?"
        assert data["revision"] == 1

        # Verify urika.toml actually changed
        toml_path = _project_dir(urika_env) / "urika.toml"
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)
        assert toml_data["project"]["question"] == "Does Y predict Z?"

    def test_update_description(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "description",
                "--value",
                "A new description",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["field"] == "description"
        assert data["new_value"] == "A new description"

    def test_update_mode(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "mode",
                "--value",
                "confirmatory",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["field"] == "mode"
        assert data["new_value"] == "confirmatory"

        # Verify urika.toml
        toml_path = _project_dir(urika_env) / "urika.toml"
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)
        assert toml_data["project"]["mode"] == "confirmatory"

    def test_update_with_reason(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "New question?",
                "--reason",
                "Refined hypothesis",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["reason"] == "Refined hypothesis"

    def test_update_unchanged_value(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        # The project question is "Does X?"
        result = runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "Does X?",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["unchanged"] is True

    def test_update_no_flags_json_errors(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        # JSON mode requires --field and --value
        result = runner.invoke(
            cli,
            ["update", "test-proj", "--json"],
            env=urika_env,
        )
        assert result.exit_code != 0

    def test_update_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "update",
                "no-such-project",
                "--field",
                "question",
                "--value",
                "test",
                "--json",
            ],
            env=urika_env,
        )
        assert result.exit_code != 0

    def test_update_history_empty(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli, ["update", "test-proj", "--history"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "No revisions" in result.output

    def test_update_history_after_change(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        # Make a change first
        runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "New Q?",
                "--json",
            ],
            env=urika_env,
        )
        result = runner.invoke(
            cli, ["update", "test-proj", "--history"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "question" in result.output
        assert "#1" in result.output

    def test_update_history_json(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        # Make a change
        runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "Revised Q?",
                "--json",
            ],
            env=urika_env,
        )
        result = runner.invoke(
            cli, ["update", "test-proj", "--history", "--json"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "revisions" in data
        assert len(data["revisions"]) == 1
        assert data["revisions"][0]["field"] == "question"
        assert data["revisions"][0]["new_value"] == "Revised Q?"

    def test_multiple_revisions(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "First update?",
                "--json",
            ],
            env=urika_env,
        )
        runner.invoke(
            cli,
            [
                "update",
                "test-proj",
                "--field",
                "question",
                "--value",
                "Second update?",
                "--json",
            ],
            env=urika_env,
        )
        result = runner.invoke(
            cli, ["update", "test-proj", "--history", "--json"], env=urika_env
        )
        data = json.loads(result.output)
        assert len(data["revisions"]) == 2
        assert data["revisions"][0]["revision"] == 1
        assert data["revisions"][1]["revision"] == 2


# ── Dashboard command ──────────────────────────────────────────


class TestDashboardCommand:
    """The dashboard CLI now uses urika.tui.dashboard_launcher and
    the FastAPI dashboard app. Tests stub uvicorn.Server so no
    real port is bound and webbrowser.open just records the URL.
    """

    def _patch_launcher(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        import uvicorn

        class _StubServer:
            def __init__(self, config: object) -> None:
                self.config = config
                self.started = True
                # exit immediately so the CLI's wait loop returns
                self.should_exit = True

            def run(self) -> None:
                return None

        monkeypatch.setattr(uvicorn, "Server", _StubServer)

        opened: list[str] = []
        monkeypatch.setattr(
            "urika.tui.dashboard_launcher.webbrowser.open",
            lambda u: opened.append(u),
        )
        return opened

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(cli, ["dashboard", "no-such-project"], env=urika_env)
        assert result.exit_code != 0

    def test_resolves_project_and_starts_server(
        self,
        runner: CliRunner,
        urika_env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _create_project(runner, urika_env)
        opened = self._patch_launcher(monkeypatch)
        result = runner.invoke(cli, ["dashboard", "test-proj"], env=urika_env)
        assert result.exit_code == 0, result.output
        assert "Starting" in result.output
        assert "Dashboard stopped" in result.output
        # Browser opened to the project page
        assert any("/projects/test-proj" in u for u in opened)

    def test_custom_port(
        self,
        runner: CliRunner,
        urika_env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _create_project(runner, urika_env)
        opened = self._patch_launcher(monkeypatch)
        result = runner.invoke(
            cli, ["dashboard", "test-proj", "--port", "9999"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert any("http://127.0.0.1:9999" in u for u in opened)

    def test_no_project_arg_opens_projects_list(
        self,
        runner: CliRunner,
        urika_env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`urika dashboard` without a project opens /projects."""
        opened = self._patch_launcher(monkeypatch)
        result = runner.invoke(cli, ["dashboard"], env=urika_env)
        assert result.exit_code == 0, result.output
        # Some URL was opened
        assert opened, "browser should have been opened"
        # All opened URLs end with /projects (no project segment)
        for url in opened:
            assert url.endswith("/projects"), url
            # belt-and-braces: no /projects/<name>
            tail = url.rsplit("/projects", 1)[1]
            assert tail == ""


# ── Venv create command ────────────────────────────────────────


class TestVenvCreateCommand:
    def test_creates_venv_directory(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        pdir = _project_dir(urika_env)
        # Mock subprocess to avoid actually creating a venv
        with patch("urika.core.venv.subprocess.run") as mock_run:
            result = runner.invoke(
                cli, ["venv", "create", "test-proj"], env=urika_env
            )
        assert result.exit_code == 0, result.output
        assert "Created .venv" in result.output
        mock_run.assert_called_once()

        # Verify urika.toml was updated with venv=true
        toml_path = pdir / "urika.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        assert data["environment"]["venv"] is True

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["venv", "create", "no-such-project"], env=urika_env
        )
        assert result.exit_code != 0

    def test_venv_already_exists(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        pdir = _project_dir(urika_env)
        # Pre-create the .venv directory so create_project_venv returns early
        (pdir / ".venv").mkdir()
        result = runner.invoke(
            cli, ["venv", "create", "test-proj"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "Created .venv" in result.output


# ── Venv status command ────────────────────────────────────────


class TestVenvStatusCommand:
    def test_not_enabled(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        result = runner.invoke(
            cli, ["venv", "status", "test-proj"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "not enabled" in result.output

    def test_enabled_after_create(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        pdir = _project_dir(urika_env)

        # Create venv (mock subprocess)
        with patch("urika.core.venv.subprocess.run"):
            runner.invoke(cli, ["venv", "create", "test-proj"], env=urika_env)

        # Check status — toml says enabled but .venv dir may not exist
        # since subprocess was mocked. Create the directory for realism.
        (pdir / ".venv").mkdir(exist_ok=True)

        result = runner.invoke(
            cli, ["venv", "status", "test-proj"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "enabled" in result.output
        assert "exists" in result.output

    def test_enabled_but_missing_dir(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        _create_project(runner, urika_env)
        pdir = _project_dir(urika_env)

        # Manually set venv=true in urika.toml without creating .venv
        toml_path = pdir / "urika.toml"
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        data.setdefault("environment", {})["venv"] = True
        from urika.core.workspace import _write_toml

        _write_toml(toml_path, data)

        result = runner.invoke(
            cli, ["venv", "status", "test-proj"], env=urika_env
        )
        assert result.exit_code == 0, result.output
        assert "enabled" in result.output
        assert "NOT FOUND" in result.output

    def test_nonexistent_project(
        self, runner: CliRunner, urika_env: dict[str, str]
    ) -> None:
        result = runner.invoke(
            cli, ["venv", "status", "no-such-project"], env=urika_env
        )
        assert result.exit_code != 0
