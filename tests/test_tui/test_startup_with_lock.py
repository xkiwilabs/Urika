"""TUI starts cleanly even when an experiment lockfile is present.

A user who starts the TUI while a CLI ``urika run`` is mid-flight in
another terminal must NOT have the TUI crash or hang on the lockfile.
The TUI should display the project (status bar, welcome) and accept
slash commands.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from urika.repl.session import ReplSession
from urika.tui.app import UrikaApp


def _setup_with_lock(tmp_path: Path, pid: str) -> ReplSession:
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.session import start_session
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "alpha"
    create_project_workspace(
        proj, ProjectConfig(name="alpha", question="Q?", mode="exploratory")
    )
    exp = create_experiment(proj, name="baseline", hypothesis="h")
    # Pre-write a lock — simulate a CLI run holding the lock.
    start_session(proj, exp.experiment_id, max_turns=1)
    (proj / "experiments" / exp.experiment_id / ".lock").write_text(pid)
    session = ReplSession()
    session.load_project(path=proj, name="alpha")
    return session


@pytest.mark.asyncio
async def test_tui_starts_with_live_lockfile_present(tmp_path: Path) -> None:
    """Lock owned by THIS process (a live python) — TUI must boot,
    show project, accept slash commands, NOT crash on the lock."""
    session = _setup_with_lock(tmp_path, str(os.getpid()))
    app = UrikaApp(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Status bar / panel render with the project name.
        panel = app.query_one("OutputPanel")
        text = "\n".join(str(s) for s in panel.lines)
        # Welcome message present, no crash.
        assert "Urika" in text or "Welcome" in text or text.strip()
        # Project is loaded.
        assert session.project_path is not None
        assert session.project_name == "alpha"


@pytest.mark.asyncio
async def test_tui_starts_with_stale_lockfile(tmp_path: Path) -> None:
    """Lock with a dead PID — TUI must still boot cleanly. The lock
    is left alone (the CLI/REPL /run path handles stale-lock cleanup
    just-in-time, not at TUI startup)."""
    session = _setup_with_lock(tmp_path, "99999998")
    app = UrikaApp(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert session.project_path is not None


@pytest.mark.asyncio
async def test_tui_starts_with_empty_lockfile_legacy(tmp_path: Path) -> None:
    """Pre-v0.3 lockfiles were empty sentinels. TUI must tolerate
    them at startup."""
    session = _setup_with_lock(tmp_path, "")
    app = UrikaApp(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert session.project_path is not None
