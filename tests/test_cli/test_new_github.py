"""Tests for ``urika new --github`` and the github_auto_create global preference.

v0.6.0 Task 2.4. After ``urika new`` finishes creating the project, optionally
also run ``urika github init --create [--public]``. Behaviour:

- Explicit ``--github`` flag → run ``gh_create_repo`` with ``public=public-flag``.
- Explicit ``--no-github`` flag → never run.
- Neither flag → check ``[preferences] github_auto_create`` in
  ``~/.urika/settings.toml``. If true, default to running with visibility from
  ``[preferences] github_auto_create_visibility = "private"|"public"``.

Failure of ``gh_create_repo`` is NON-FATAL — the project itself was created,
only the GitHub create failed. Print the error + install hint and continue.

Tests use ``--json`` mode for deterministic non-interactive invocation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from urika.cli import cli


def _common_new_args(name: str, data_path: Path, tmp_path: Path) -> list[str]:
    """Minimum required args for ``urika new`` in --json (non-interactive) mode."""
    return [
        "new",
        name,
        "-q",
        "test question",
        "-m",
        "exploratory",
        "--data",
        str(data_path),
        "--json",
    ]


def _setup_test_data(tmp_path: Path) -> Path:
    """Tiny CSV so urika new has data to point at."""
    data = tmp_path / "stroop.csv"
    data.write_text("col1,col2\n1,2\n3,4\n")
    return data


def _setup_env(tmp_urika_home: Path, tmp_path: Path, monkeypatch) -> None:
    """Install the URIKA_PROJECTS_DIR + builder-agent guard for non-interactive runs."""
    monkeypatch.setenv("URIKA_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("URIKA_NO_BUILDER_AGENT", "1")


def test_new_github_flag_triggers_create(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """``urika new --github`` invokes gh_create_repo at the end (private default)."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="https://github.com/u/proj"),
    ) as spy:
        result = CliRunner().invoke(
            cli, _common_new_args("proj", data, tmp_path) + ["--github"]
        )
    assert result.exit_code == 0, result.output
    assert spy.called
    assert spy.call_args.kwargs.get("public") is False


def test_new_github_public_flag(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """``--github --public`` passes ``public=True`` to gh_create_repo."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)

    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="..."),
    ) as spy:
        result = CliRunner().invoke(
            cli,
            _common_new_args("proj-pub", data, tmp_path) + ["--github", "--public"],
        )
    assert result.exit_code == 0, result.output
    assert spy.call_args.kwargs.get("public") is True


def test_new_no_github_skips_when_preference_enabled(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """When ``--no-github`` is explicit, the global preference is ignored."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)
    # Enable the global preference — should be overridden by --no-github.
    settings_file = tmp_urika_home / "settings.toml"
    settings_file.write_text(
        "[preferences]\n"
        "github_auto_create = true\n"
        'github_auto_create_visibility = "private"\n'
    )
    with patch("urika.core.git.gh_create_repo") as spy:
        result = CliRunner().invoke(
            cli, _common_new_args("proj-no", data, tmp_path) + ["--no-github"]
        )
    assert result.exit_code == 0, result.output
    spy.assert_not_called()


def test_new_no_flag_no_preference_skips_gh(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """No ``--github`` flag AND no global preference: gh_create_repo never called."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)
    with patch("urika.core.git.gh_create_repo") as spy:
        result = CliRunner().invoke(cli, _common_new_args("proj-plain", data, tmp_path))
    assert result.exit_code == 0, result.output
    spy.assert_not_called()


def test_global_preference_triggers_github_auto_create(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """``[preferences] github_auto_create = true`` makes ``urika new`` default to --github."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)
    settings_file = tmp_urika_home / "settings.toml"
    settings_file.write_text(
        "[preferences]\n"
        "github_auto_create = true\n"
        'github_auto_create_visibility = "private"\n'
    )
    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="..."),
    ) as spy:
        result = CliRunner().invoke(cli, _common_new_args("proj-auto", data, tmp_path))
    assert result.exit_code == 0, result.output
    assert spy.called
    # visibility from preference defaults to private
    assert spy.call_args.kwargs.get("public") is False


def test_global_preference_public_visibility(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """``github_auto_create_visibility = "public"`` flips ``public=True``."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)
    settings_file = tmp_urika_home / "settings.toml"
    settings_file.write_text(
        "[preferences]\n"
        "github_auto_create = true\n"
        'github_auto_create_visibility = "public"\n'
    )
    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(ok=True, repo_url="..."),
    ) as spy:
        CliRunner().invoke(cli, _common_new_args("proj-pub-auto", data, tmp_path))
    assert spy.called
    assert spy.call_args.kwargs.get("public") is True


def test_new_github_failure_is_non_fatal(
    tmp_urika_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """When gh_create_repo returns ok=False, ``urika new`` STILL succeeds (project created)."""
    _setup_env(tmp_urika_home, tmp_path, monkeypatch)
    data = _setup_test_data(tmp_path)
    from urika.core.git import GhCreateResult

    with patch(
        "urika.core.git.gh_create_repo",
        return_value=GhCreateResult(
            ok=False,
            error="gh CLI not found",
            install_hint="Install: brew install gh",
        ),
    ):
        result = CliRunner().invoke(
            cli, _common_new_args("proj-fail", data, tmp_path) + ["--github"]
        )
    # Project created even though gh failed.
    assert result.exit_code == 0, result.output
    # The error message + install hint surfaced.
    combined = (result.output or "") + (result.stderr if result.stderr_bytes else "")
    assert "gh CLI not found" in combined
    assert "Install:" in combined
    # And the project directory was actually written.
    project_dir = tmp_path / "projects" / "proj-fail"
    assert (project_dir / "urika.toml").exists()
