"""Tests for --json flag on CLI commands."""

from __future__ import annotations

import json

from click.testing import CliRunner

from urika.cli import cli


def test_list_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "projects" in data


def test_tools_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["tools", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "tools" in data
    assert len(data["tools"]) >= 16


def test_config_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "--show", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, dict)


def test_setup_json():
    runner = CliRunner()
    result = runner.invoke(cli, ["setup", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "packages" in data
    assert "hardware" in data
