"""Tests for ``urika upgrade`` — idempotent v0.x project migration.

v0.10.0 Phase 1. The v1.0 promise is that any v0.x project upgrades via
``urika upgrade`` (auto-migrate, idempotent). These tests drive the
command over the legacy fixtures and assert:

* ``schema_version`` is stamped to the current version,
* legacy ``leaderboard.json`` ``entries`` is rewritten to ``ranking`` on
  disk,
* ``urika status`` / ``inspect`` still work after the upgrade,
* a second run is a byte-for-byte no-op (idempotency),
* ``--all`` upgrades every registered project,
* an already-current project is a no-op.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli
from urika.core.models import current_schema_version
from urika.core.registry import ProjectRegistry


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "legacy"


def _copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES_DIR / name
    target = dest / name
    shutil.copytree(src, target)
    return target


def _schema_version_on_disk(project_dir: Path) -> str:
    with open(project_dir / "urika.toml", "rb") as f:
        data = tomllib.load(f)
    return data["project"].get("schema_version", "")


@pytest.fixture
def isolated_urika_home(tmp_path, monkeypatch):
    home = tmp_path / "urika-home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


def _register(name: str, path: Path) -> None:
    ProjectRegistry().register(name, path)


# ── Stamping the schema version ──────────────────────────────────


def test_upgrade_stamps_schema_version(tmp_path, isolated_urika_home) -> None:
    proj = _copy_fixture("v050-pre-labbook", tmp_path)
    _register("v050-pre-labbook", proj)
    assert _schema_version_on_disk(proj) == ""

    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade", "v050-pre-labbook"])

    assert result.exit_code == 0, result.output
    assert _schema_version_on_disk(proj) == current_schema_version()


def test_upgrade_preserves_existing_config_fields(
    tmp_path, isolated_urika_home
) -> None:
    proj = _copy_fixture("v090-pre-uncertainty", tmp_path)
    _register("v090-pre-uncertainty", proj)

    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade", "v090-pre-uncertainty"])
    assert result.exit_code == 0, result.output

    with open(proj / "urika.toml", "rb") as f:
        data = tomllib.load(f)
    # Original fields survive the stamp/rewrite.
    assert data["project"]["mode"] == "confirmatory"
    assert data["preferences"]["audience"] == "expert"
    assert data["project"]["data_paths"] == ["data/sample.csv"]


def test_upgrade_leaves_run_records_untouched(tmp_path, isolated_urika_home) -> None:
    """v090 runs lack metrics_with_uncertainty — upgrade must not touch
    the progress.json run records, only the version stamp."""
    proj = _copy_fixture("v090-pre-uncertainty", tmp_path)
    _register("v090-pre-uncertainty", proj)
    prog = proj / "experiments" / "exp-001-models" / "progress.json"
    before = prog.read_bytes()

    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade", "v090-pre-uncertainty"])
    assert result.exit_code == 0, result.output
    assert prog.read_bytes() == before


# ── Leaderboard entries -> ranking rewrite ───────────────────────


def test_upgrade_rewrites_leaderboard_entries(tmp_path, isolated_urika_home) -> None:
    proj = _copy_fixture("v080-old-leaderboard-entries", tmp_path)
    _register("v080-old-leaderboard-entries", proj)

    lb_path = proj / "leaderboard.json"
    before = json.loads(lb_path.read_text())
    assert "entries" in before and "ranking" not in before

    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade", "v080-old-leaderboard-entries"])
    assert result.exit_code == 0, result.output

    after = json.loads(lb_path.read_text())
    assert "entries" not in after
    assert "ranking" in after
    assert after["ranking"] == before["entries"]


# ── status / inspect still work post-upgrade ─────────────────────


def test_status_works_after_upgrade(tmp_path, isolated_urika_home) -> None:
    proj = _copy_fixture("v080-old-leaderboard-entries", tmp_path)
    _register("v080-old-leaderboard-entries", proj)

    runner = CliRunner()
    up = runner.invoke(cli, ["upgrade", "v080-old-leaderboard-entries"])
    assert up.exit_code == 0, up.output

    st = runner.invoke(cli, ["status", "v080-old-leaderboard-entries", "--json"])
    assert st.exit_code == 0, st.output
    data = json.loads(st.output)
    assert data["project"] == "v080-old-leaderboard-entries"

    ins = runner.invoke(cli, ["inspect", "v080-old-leaderboard-entries", "--json"])
    assert ins.exit_code == 0, ins.output


# ── Idempotency ──────────────────────────────────────────────────


def test_upgrade_is_idempotent_byte_identical(tmp_path, isolated_urika_home) -> None:
    proj = _copy_fixture("v080-old-leaderboard-entries", tmp_path)
    _register("v080-old-leaderboard-entries", proj)

    runner = CliRunner()
    first = runner.invoke(cli, ["upgrade", "v080-old-leaderboard-entries"])
    assert first.exit_code == 0, first.output

    # Snapshot every file after the first upgrade.
    def _snapshot() -> dict[str, bytes]:
        return {
            str(p.relative_to(proj)): p.read_bytes()
            for p in sorted(proj.rglob("*"))
            if p.is_file()
        }

    after_first = _snapshot()

    second = runner.invoke(cli, ["upgrade", "v080-old-leaderboard-entries"])
    assert second.exit_code == 0, second.output
    after_second = _snapshot()

    assert after_first == after_second, "second upgrade mutated files"


def test_upgrade_second_run_reports_noop_json(tmp_path, isolated_urika_home) -> None:
    proj = _copy_fixture("v080-old-leaderboard-entries", tmp_path)
    _register("v080-old-leaderboard-entries", proj)

    runner = CliRunner()
    runner.invoke(cli, ["upgrade", "v080-old-leaderboard-entries"])

    second = runner.invoke(cli, ["upgrade", "v080-old-leaderboard-entries", "--json"])
    assert second.exit_code == 0, second.output
    payload = json.loads(second.output)
    entry = payload[0] if isinstance(payload, list) else payload
    assert entry["already_current"] is True
    assert entry["migrations"] == []


def test_already_current_project_is_noop(tmp_path, isolated_urika_home) -> None:
    """A project already stamped at the current version short-circuits."""
    proj = _copy_fixture("v090-pre-uncertainty", tmp_path)
    # Pre-stamp it to current.
    toml = (proj / "urika.toml").read_text()
    toml = toml.replace(
        "[preferences]",
        f'schema_version = "{current_schema_version()}"\n\n[preferences]',
    )
    (proj / "urika.toml").write_text(toml)
    _register("v090-pre-uncertainty", proj)

    before = (proj / "urika.toml").read_bytes()
    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade", "v090-pre-uncertainty", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    entry = payload[0] if isinstance(payload, list) else payload
    assert entry["already_current"] is True
    # No-op: urika.toml unchanged.
    assert (proj / "urika.toml").read_bytes() == before


# ── --all ────────────────────────────────────────────────────────


def test_upgrade_all_upgrades_every_project(tmp_path, isolated_urika_home) -> None:
    names = [
        "v080-old-leaderboard-entries",
        "v050-pre-labbook",
        "v090-pre-uncertainty",
    ]
    paths = {}
    for name in names:
        paths[name] = _copy_fixture(name, tmp_path)
        _register(name, paths[name])

    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade", "--all", "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert {e["project"] for e in payload} == set(names)
    for name in names:
        assert _schema_version_on_disk(paths[name]) == current_schema_version()


def test_upgrade_requires_project_or_all(tmp_path, isolated_urika_home) -> None:
    """With no project and no --all, the command must error clearly."""
    runner = CliRunner()
    result = runner.invoke(cli, ["upgrade"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
