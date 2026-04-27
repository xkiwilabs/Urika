"""Structural test that proves a dashboard-spawned child survives our exit.

This test does NOT exercise an actual dashboard restart — that would
require killing the test process. Instead it asserts the structural
invariant that makes the survival work: the child runs in its own
session / process group, so terminal signals to the dashboard are
not delivered to the child via the controlling-terminal signal path,
and the child writes directly to its log file (no pipe to receive
SIGPIPE on our exit).

The helper ``_spawn_detached`` is the foundation of every
dashboard-launched agent run; if these invariants regress, every
``urika run`` started from the browser becomes vulnerable to being
killed by a dashboard restart again.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from urika.dashboard.runs import _spawn_detached


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX session semantics")
def test_dashboard_exit_does_not_kill_child(tmp_path: Path) -> None:
    """The spawned child must be in a different session/process group
    than the test process. That's the structural property that
    prevents a Ctrl+C in the dashboard terminal from propagating
    to the child."""
    log_path = tmp_path / "child.log"
    lock_path = tmp_path / ".child.lock"

    # A short-lived child is enough — we only need to inspect its
    # process-group while it's alive.
    cmd = [sys.executable, "-u", "-c", "import time; time.sleep(2)"]
    pid = _spawn_detached(
        cmd, env=os.environ.copy(), log_path=log_path, lock_path=lock_path
    )

    try:
        # Process-group of the child must NOT match ours. ``getpgid(pid)``
        # returns the child's pgid; if equal, the child is in our group
        # and would receive SIGINT/SIGHUP from our terminal.
        child_pgid = os.getpgid(pid)
        our_pgid = os.getpgid(0)
        assert child_pgid != our_pgid, (
            f"child pgid {child_pgid} == our pgid {our_pgid} — "
            "child would inherit terminal signals from the dashboard"
        )

        # The lock file must contain the PID — the active-ops banner
        # uses this to report the running operation across restarts.
        assert lock_path.read_text(encoding="utf-8") == str(pid)
    finally:
        # Reap the child so we don't leave a zombie behind.
        try:
            os.kill(pid, 15)  # SIGTERM
        except ProcessLookupError:
            pass
        # Wait briefly for the reaper thread to clean up the lock.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: file-fd plumbing")
def test_child_stdout_writes_directly_to_log_file(tmp_path: Path) -> None:
    """The child must write to the log file directly, not through a
    pipe. We verify by spawning a child that prints a known token,
    waiting for it to exit, and checking the log file contents.

    If a pipe were involved, a draining thread inside the dashboard
    would be the one writing the log; the dashboard exit (or here,
    ``_spawn_detached`` returning before the drainer reads anything)
    would lose output. With direct-to-file, the child's output
    survives even before the parent waits.
    """
    log_path = tmp_path / "child.log"
    lock_path = tmp_path / ".child.lock"

    token = "URIKA-DETACHED-TOKEN-9c7e1"
    cmd = [sys.executable, "-u", "-c", f"print({token!r})"]
    pid = _spawn_detached(
        cmd, env=os.environ.copy(), log_path=log_path, lock_path=lock_path
    )

    # Wait for the child to finish writing and the reaper to clean up.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)

    # Give the OS a beat to flush, then read back.
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if log_path.is_file() and token in log_path.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)

    assert log_path.is_file()
    assert token in log_path.read_text(encoding="utf-8")
