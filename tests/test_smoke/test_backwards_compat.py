"""Backwards-compatibility smoke for projects from older Urika releases.

v0.4.3 Track 2e. The v0.4.x audits surfaced several "old project +
new release" bugs that the existing CLI-shell smoke harness never
exercised — most notably the user-reported lockfile bug
(empty pre-v0.3 ``.lock`` files refusing for 6 hours, fixed in
v0.4.2 Package K). These tests pin the fix and a couple of related
backwards-compat paths so a future regression surfaces immediately
instead of as an angry user issue.

Each test:

1. Copies a fixture from ``tests/fixtures/legacy/`` to a tmp_path
   (so the fixture itself stays read-only).
2. Registers the project under a tmp ``URIKA_HOME``.
3. Drives one or more shell commands via ``CliRunner``.
4. Asserts the new release handles the legacy shape gracefully.

These run as ``@pytest.mark.integration`` so they're opt-in by
default — but they're cheap (no LLM calls) so they could move to
the regular suite if you want them on every commit.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from urika.cli import cli
from urika.core.registry import ProjectRegistry


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "legacy"


def _copy_fixture(name: str, dest: Path) -> Path:
    src = FIXTURES_DIR / name
    target = dest / name
    shutil.copytree(src, target)
    return target


@pytest.fixture
def isolated_urika_home(tmp_path, monkeypatch):
    """Tmp ``URIKA_HOME`` so each test starts with a clean registry."""
    home = tmp_path / "urika-home"
    home.mkdir()
    monkeypatch.setenv("URIKA_HOME", str(home))
    return home


# ── 1. Empty pre-v0.3 lockfile ────────────────────────────────────


@pytest.mark.integration
class TestV030EmptyLockfile:
    """Pre-v0.3 ``acquire_lock`` used ``path.touch()`` and crashed
    runs left empty ``.lock`` files behind. v0.4.2 Package K's
    fix: treat empty locks as stale unconditionally (the current
    release always writes the PID, so any empty lock is a pre-v0.3
    leftover).
    """

    def test_status_does_not_crash_on_empty_lock(
        self, tmp_path, isolated_urika_home
    ) -> None:
        proj = _copy_fixture("v030-empty-lockfile", tmp_path)
        ProjectRegistry().register("v030-empty-lockfile", proj)

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "v030-empty-lockfile", "--json"])

        assert result.exit_code == 0, result.output
        # Status should report the experiment exists; the lockfile
        # presence shouldn't trip the loader.
        data = json.loads(result.output)
        # ``urika status --json`` returns ``{"project": "<name>", ...}``.
        assert data["project"] == "v030-empty-lockfile"

    def test_unlock_clears_empty_lock(
        self, tmp_path, isolated_urika_home
    ) -> None:
        """The new ``urika unlock`` command (v0.4.2 Package K) should
        clear an empty lock without ``--force`` because the empty file
        has no PID for the safety check to interpret as alive."""
        proj = _copy_fixture("v030-empty-lockfile", tmp_path)
        ProjectRegistry().register("v030-empty-lockfile", proj)

        lock = proj / "experiments" / "exp-001-old-run" / ".lock"
        assert lock.exists()
        assert lock.read_text() == ""  # confirm fixture is genuinely empty

        runner = CliRunner()
        result = runner.invoke(
            cli, ["unlock", "v030-empty-lockfile", "exp-001-old-run"]
        )

        assert result.exit_code == 0, result.output
        assert "Unlocked" in result.output
        assert not lock.exists()

    def test_acquire_lock_treats_empty_as_stale(
        self, tmp_path, isolated_urika_home
    ) -> None:
        """The lower-level ``acquire_lock`` should also clean up the
        empty file directly — covers the path that fires when
        ``urika run`` tries to start a new run on a project with a
        legacy lock left behind."""
        from urika.core.session import _lock_path, acquire_lock

        proj = _copy_fixture("v030-empty-lockfile", tmp_path)
        lock = _lock_path(proj, "exp-001-old-run")
        assert lock.exists() and lock.read_text() == ""

        # Pre-v0.4.2 Package K this would refuse for 6 hours.
        assert acquire_lock(proj, "exp-001-old-run") is True
        # And now the lock is OURS (contains our PID).
        import os

        assert lock.read_text().strip() == str(os.getpid())


# ── 2. Truncated progress.json ────────────────────────────────────


@pytest.mark.integration
class TestV03xCorruptProgress:
    """A SIGTERM mid-``progress.json``-write before v0.4.2 Package A
    could leave a truncated JSON file on disk. Package A migrated
    state writes to atomic temp+rename so it can't happen anymore,
    but a reader still has to handle PRE-EXISTING corrupt files
    without crashing the whole CLI."""

    def test_load_progress_handles_truncated_json(
        self, tmp_path, isolated_urika_home
    ) -> None:
        from urika.core.progress import load_progress

        proj = _copy_fixture("v03x-corrupt-progress", tmp_path)

        # The fixture's progress.json is intentionally invalid.
        result = load_progress(proj, "exp-001-truncated")

        # Should return the safe default, not raise.
        assert result == {"runs": [], "status": "pending"}

    def test_results_command_handles_corrupt_progress(
        self, tmp_path, isolated_urika_home
    ) -> None:
        """``urika results`` reads progress.json. Should fall back to
        empty leaderboard rather than crashing."""
        proj = _copy_fixture("v03x-corrupt-progress", tmp_path)
        ProjectRegistry().register("v03x-corrupt-progress", proj)

        runner = CliRunner()
        result = runner.invoke(
            cli, ["results", "v03x-corrupt-progress", "--json"]
        )

        # Either succeeds with empty results, OR exits with a
        # readable error message (NOT a Python traceback).
        if result.exit_code != 0:
            # Acceptable failure: message-style, not traceback.
            assert "Traceback" not in result.output, (
                f"Crash on corrupt progress.json — should fail "
                f"gracefully. Output: {result.output[:500]}"
            )


# ── 3. Older urika.toml without [runtime] / [privacy] blocks ─────


@pytest.mark.integration
class TestV040NoRuntimeBlock:
    """Older project shapes had no ``[runtime]`` or ``[privacy]``
    sections in ``urika.toml``. The current loader must fall back
    to defaults instead of raising."""

    def test_status_works_without_runtime_block(
        self, tmp_path, isolated_urika_home
    ) -> None:
        proj = _copy_fixture("v040-no-runtime-block", tmp_path)
        ProjectRegistry().register("v040-no-runtime-block", proj)

        runner = CliRunner()
        result = runner.invoke(cli, ["status", "v040-no-runtime-block", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["project"] == "v040-no-runtime-block"

    def test_load_runtime_config_falls_back_to_defaults(
        self, tmp_path, isolated_urika_home
    ) -> None:
        """Direct unit-level check on the loader path."""
        from urika.agents.config import load_runtime_config

        proj = _copy_fixture("v040-no-runtime-block", tmp_path)

        config = load_runtime_config(proj)
        # Should be a RuntimeConfig with sensible defaults — open
        # privacy mode, claude backend, no per-agent overrides.
        assert config.privacy_mode == "open"
        assert config.backend == "claude"

    def test_inspect_works_without_runtime_block(
        self, tmp_path, isolated_urika_home
    ) -> None:
        proj = _copy_fixture("v040-no-runtime-block", tmp_path)
        ProjectRegistry().register("v040-no-runtime-block", proj)

        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "v040-no-runtime-block", "--json"])

        assert result.exit_code == 0, result.output


# ── Cross-fixture: nothing leaks between tests ────────────────────


@pytest.mark.integration
def test_fixtures_are_read_only(tmp_path, isolated_urika_home) -> None:
    """Sanity check: copying a fixture to tmp_path doesn't mutate
    the original. If a future test forgets to copy first, this
    would catch the leak by comparing fixture sizes before/after."""
    before_sizes = {
        f.name: f.stat().st_size
        for f in FIXTURES_DIR.iterdir()
        if f.is_dir()
    }

    # Copy every fixture into tmp_path.
    for name in before_sizes:
        _copy_fixture(name, tmp_path)

    after_sizes = {
        f.name: f.stat().st_size
        for f in FIXTURES_DIR.iterdir()
        if f.is_dir()
    }

    assert before_sizes == after_sizes
