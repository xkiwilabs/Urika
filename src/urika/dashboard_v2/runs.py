"""Subprocess spawn helper for browser-launched experiment runs.

The dashboard kicks off ``urika run`` as a subprocess, owns its
stdout via a daemon thread, and writes that to ``<exp>/run.log`` so
the SSE log tailer (Task 6.4) has something to read. The
subprocess outlives the HTTP request — dashboards run in
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

    def _drain() -> None:
        with open(log_path, "a", buffering=1, encoding="utf-8") as f:
            try:
                if proc.stdout is not None:
                    for line in proc.stdout:
                        f.write(line)
                        f.flush()
            finally:
                proc.wait()
                # Remove .lock so the SSE tailer knows the run is done.
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    _DAEMON_THREADS.append(t)

    return proc.pid
