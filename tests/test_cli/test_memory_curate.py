"""Tests for ``urika memory curate [--apply]`` (v0.5.0 Task 2.8).

The CLI sub-command is a thin wrapper around
:func:`urika.core.memory_curator.run_curator`. Dry-run is the default;
``--apply`` commits the agent's decisions to disk. We monkeypatch
``run_curator`` at the module level so we never hit a real agent.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from urika.cli import cli
from urika.core import project_memory as pm
from urika.core.models import ProjectConfig
from urika.core.registry import ProjectRegistry
from urika.core.workspace import create_project_workspace


def _setup(tmp_path: Path, monkeypatch) -> Path:
    """Register a project named ``proj`` with one seed memory entry."""
    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "urika-home"))
    project_dir = tmp_path / "proj"
    config = ProjectConfig(
        name="proj",
        question="q",
        mode="exploratory",
        data_paths=[],
    )
    create_project_workspace(project_dir, config)
    ProjectRegistry().register("proj", project_dir)
    pm.save_entry(project_dir, mem_type="user", description="t", body="b")
    return project_dir


def test_curate_dry_run_prints_decisions(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(
            decisions=[
                {
                    "action": "archive",
                    "filename": "user_t.md",
                    "reason": "stale entry",
                }
            ],
            applied=False,
        )

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    result = CliRunner().invoke(cli, ["memory", "curate", "proj"])
    assert result.exit_code == 0, result.output
    assert "archive" in result.output
    assert "stale entry" in result.output
    assert "dry-run" in result.output
    # User hint to commit appears.
    assert "--apply" in result.output


def test_curate_apply_invokes_with_apply_true(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        captured["apply"] = apply
        captured["project_dir"] = project_dir
        return CuratorResult(decisions=[], applied=apply)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    result = CliRunner().invoke(cli, ["memory", "curate", "proj", "--apply"])
    assert result.exit_code == 0, result.output
    assert captured["apply"] is True


def test_curate_handles_error_result(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[], applied=False, error="boom")

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    result = CliRunner().invoke(cli, ["memory", "curate", "proj"])
    assert result.exit_code == 1
    # Click writes secho(err=True) to stderr; CliRunner captures both in `result.output`
    # by default via mix_stderr=True, but the message must surface somewhere.
    combined = result.output + (
        result.stderr if result.stderr_bytes is not None else ""
    )
    assert "boom" in combined


def test_curate_no_decisions_message(tmp_path: Path, monkeypatch) -> None:
    """When the curator returns zero decisions, the CLI says so plainly
    rather than printing an empty decisions list with the --apply hint."""
    _setup(tmp_path, monkeypatch)

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[], applied=False)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    result = CliRunner().invoke(cli, ["memory", "curate", "proj"])
    assert result.exit_code == 0, result.output
    assert "no changes" in result.output.lower()
    # Don't dangle a misleading --apply hint when there's nothing to apply.
    assert "Re-run with --apply" not in result.output


def test_curate_renders_merge_decision(tmp_path: Path, monkeypatch) -> None:
    """Merge decisions name an ``into`` target, not ``filename`` — the
    renderer should still produce a useful one-liner."""
    _setup(tmp_path, monkeypatch)

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(
            decisions=[
                {
                    "action": "merge",
                    "into": "user_keep.md",
                    "from": ["user_drop.md"],
                    "reason": "duplicate",
                }
            ],
            applied=False,
        )

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    result = CliRunner().invoke(cli, ["memory", "curate", "proj"])
    assert result.exit_code == 0, result.output
    assert "merge" in result.output
    assert "user_keep.md" in result.output
    assert "duplicate" in result.output


def test_curate_without_project_prompts_or_uses_single(
    tmp_path: Path, monkeypatch
) -> None:
    """A single registered project is auto-selected so ``urika memory
    curate`` works without an explicit project arg (mirrors how the
    other memory subcommands behave)."""
    _setup(tmp_path, monkeypatch)

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        return CuratorResult(decisions=[], applied=False)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)

    result = CliRunner().invoke(cli, ["memory", "curate"])
    assert result.exit_code == 0, result.output
    # Silently uses the only registered project ``proj``.
    assert "no changes" in result.output.lower() or "0 decision" in result.output


# Smoke: sanity that we get JSON-able decision data via the fake.
def test_curate_decisions_dict_passthrough(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    seen: list[dict] = []

    async def fake(project_dir, runner, apply=False):
        from urika.core.memory_curator import CuratorResult

        d = [
            {
                "action": "flag_stale",
                "filename": "user_t.md",
                "reason": "out of date",
            }
        ]
        seen.extend(d)
        return CuratorResult(decisions=d, applied=False)

    monkeypatch.setattr("urika.core.memory_curator.run_curator", fake)
    result = CliRunner().invoke(cli, ["memory", "curate", "proj"])
    assert result.exit_code == 0, result.output
    assert "flag_stale" in result.output
    # Decisions remain a list-of-dicts (json-safe).
    json.dumps(seen)
