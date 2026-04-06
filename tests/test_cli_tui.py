"""Tests for the TUI CLI command."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from urika.cli import cli


def test_tui_command_exists():
    """The 'tui' command is registered."""
    runner = CliRunner()
    result = runner.invoke(cli, ["tui", "--help"])
    assert result.exit_code == 0
    assert "Launch the interactive Urika TUI" in result.output


def test_tui_no_binary_shows_error():
    """When no TUI binary is found, show helpful error."""
    runner = CliRunner()
    with patch("urika.cli.tui._find_tui_binary", return_value=None), \
         patch("urika.cli.tui.shutil.which", return_value=None), \
         patch("urika.cli.tui.Path.exists", return_value=False):
        result = runner.invoke(cli, ["tui"])
    assert result.exit_code != 0


def test_tui_with_binary(tmp_path: Path):
    """When binary exists, subprocess.run is called."""
    runner = CliRunner()
    fake_bin = tmp_path / "urika-tui"
    fake_bin.write_text("#!/bin/sh\nexit 0")
    fake_bin.chmod(0o755)

    with patch("urika.cli.tui._find_tui_binary", return_value=str(fake_bin)), \
         patch("urika.cli.tui.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        runner.invoke(cli, ["tui"])
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert str(fake_bin) in args


def test_run_legacy_flag():
    """The --legacy flag is accepted by the run command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert "--legacy" in result.output


def test_run_legacy_flag_accepted():
    """Passing --legacy doesn't crash (no project needed for help check)."""
    runner = CliRunner()
    # Just verify the flag is accepted — actual run needs a project
    result = runner.invoke(cli, ["run", "--legacy", "--help"])
    assert result.exit_code == 0
