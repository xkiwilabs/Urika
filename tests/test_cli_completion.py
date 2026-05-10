"""Tests for the ``urika completion`` group (v0.4 Track 4)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def urika_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Click 8.3's bash completion class fails to generate on Windows "
        "(zsh and fish work). Bash completion isn't a native Windows "
        "use case — Windows users either run urika in PowerShell/cmd "
        "(no bash) or in WSL (which has its own bash). When invoked "
        "inside WSL the test passes; only the CPython-on-Windows path "
        "trips it. Not worth maintaining a Windows-specific bash "
        "fallback."
    ),
)
def test_completion_script_bash_returns_non_empty():
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "script", "bash"])
    assert result.exit_code == 0, result.output
    # Click 8 emits a function name like ``_urika_completion``.
    assert "_urika_completion" in result.output
    assert "complete" in result.output


def test_completion_script_zsh_returns_non_empty():
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "script", "zsh"])
    assert result.exit_code == 0
    assert "_urika_completion" in result.output


def test_completion_script_fish_returns_non_empty():
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "script", "fish"])
    assert result.exit_code == 0
    # fish completions reference 'complete' for builtins
    assert "complete" in result.output.lower()


def test_completion_install_writes_to_urika_home(urika_home):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "install", "bash"])
    assert result.exit_code == 0
    out_path = urika_home / "completions" / "urika.bash"
    assert out_path.exists()
    body = out_path.read_text(encoding="utf-8")
    assert "_urika_completion" in body
    # User-facing help points at the source command.
    assert "source" in result.output


def test_completion_install_unknown_shell_rejected():
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "install", "csh"])
    # Click rejects with exit code 2 (usage error) when the choice
    # doesn't match.
    assert result.exit_code != 0


def test_completion_uninstall_removes_installed_script(urika_home):
    from urika.cli import cli

    runner = CliRunner()
    runner.invoke(cli, ["completion", "install", "bash"])
    out_path = urika_home / "completions" / "urika.bash"
    assert out_path.exists()
    result = runner.invoke(cli, ["completion", "uninstall", "bash"])
    assert result.exit_code == 0
    assert not out_path.exists()


def test_completion_uninstall_no_files_is_no_op(urika_home):
    from urika.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "uninstall"])
    assert result.exit_code == 0
    assert "No installed completion scripts" in result.output
