"""Subprocess spawn helpers for browser-launched agent runs.

The dashboard kicks off CLI commands (``urika run``, ``urika finalize``,
``urika present``) as subprocesses, owns their stdout via a daemon thread,
and writes that to a log file so SSE log tailers have something to read.
Each spawn writes a ``.lock`` file alongside its log; the lock is removed
when the subprocess exits, so SSE tailers can detect completion.
The subprocess outlives the HTTP request — dashboards run in
long-lived uvicorn workers so the OS keeps the child alive.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path


# Tracked only so tests can join/inspect the drainer thread; not used at runtime.
_DAEMON_THREADS: list[threading.Thread] = []


def _start_drainer(
    proc: subprocess.Popen, log_path: Path, lock_path: Path
) -> threading.Thread:
    """Spawn a daemon thread that pipes ``proc.stdout`` into ``log_path``.

    When the subprocess exits, ``lock_path`` is removed so SSE tailers
    can emit a completion event. The thread reference is stashed in
    ``_DAEMON_THREADS`` so tests can join on it.
    """

    def _drain() -> None:
        with open(log_path, "a", buffering=1, encoding="utf-8") as f:
            try:
                if proc.stdout is not None:
                    for line in proc.stdout:
                        f.write(line)
                        f.flush()
            finally:
                proc.wait()
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    _DAEMON_THREADS.append(t)
    return t


def spawn_experiment_run(
    project_name: str,
    project_path: Path,
    experiment_id: str,
    *,
    executable: str | None = None,
) -> int:
    """Spawn ``urika run <project> --experiment <exp_id>`` as a subprocess.

    Writes the PID to ``<exp>/.lock`` and starts a daemon thread that
    reads the subprocess's stdout into ``<exp>/run.log``. Returns the
    PID so the caller can stash it / kill it later.

    The subprocess receives ``URIKA_NO_TEE=1`` in its environment so
    that ``urika run`` skips its own ``OrchestratorLogger`` tee and
    we (the dashboard) remain the sole writer to ``run.log``.
    """
    exp_dir = project_path / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / "run.log"
    lock_path = exp_dir / ".lock"

    cmd = [
        executable or sys.executable,
        "-m",
        "urika",
        "run",
        project_name,
        "--experiment",
        experiment_id,
    ]

    env = os.environ.copy()
    env["URIKA_NO_TEE"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        env=env,
    )

    lock_path.write_text(str(proc.pid), encoding="utf-8")
    _start_drainer(proc, log_path, lock_path)
    return proc.pid


def spawn_finalize(
    project_name: str,
    project_path: Path,
    *,
    instructions: str = "",
    audience: str | None = None,
    executable: str | None = None,
) -> int:
    """Spawn ``urika finalize <project> --json`` as a subprocess.

    Writes the PID to ``<project>/projectbook/.finalize.lock`` and tees
    stdout to ``<project>/projectbook/finalize.log``. The lock is
    removed when the subprocess exits. Returns the PID.

    ``audience`` follows the finalize CLI allow-list
    (``{"novice", "standard", "expert"}``), which differs from the
    core/models.py ``VALID_AUDIENCES`` set; callers should validate
    against the CLI's set before invoking.
    """
    book_dir = project_path / "projectbook"
    book_dir.mkdir(parents=True, exist_ok=True)
    log_path = book_dir / "finalize.log"
    lock_path = book_dir / ".finalize.lock"

    cmd = [
        executable or sys.executable,
        "-m",
        "urika",
        "finalize",
        project_name,
        "--json",
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])
    if audience:
        cmd.extend(["--audience", audience])

    env = os.environ.copy()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        env=env,
    )
    lock_path.write_text(str(proc.pid), encoding="utf-8")
    _start_drainer(proc, log_path, lock_path)
    return proc.pid
