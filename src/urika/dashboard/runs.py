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


def _build_env(*, no_tee: bool = False) -> dict[str, str]:
    """Environment for spawned urika subprocesses.

    Always sets ``PYTHONUNBUFFERED=1`` so the daemon drainer can tail
    stdout in real time (block buffering on a piped child stdout would
    otherwise hold output in 8KB chunks until process exit). When
    ``no_tee=True`` also sets ``URIKA_NO_TEE`` so ``urika run`` skips
    its own log tee — the dashboard becomes the sole writer.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if no_tee:
        env["URIKA_NO_TEE"] = "1"
    return env


def _python_cmd(executable: str | None) -> list[str]:
    """Base command for spawning ``python -u -m urika ...``.

    The ``-u`` flag disables Python's stdout/stderr buffering in the
    child so a piped stdout streams line-by-line into the drainer
    thread instead of being held in 8KB blocks until process exit.
    """
    return [executable or sys.executable, "-u", "-m", "urika"]


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
    instructions: str = "",
    max_turns: int | None = None,
    audience: str | None = None,
    auto: bool = False,
    max_experiments: int | None = None,
    review_criteria: bool = False,
    resume: bool = False,
    executable: str | None = None,
) -> int:
    """Spawn ``urika run <project> --experiment <exp_id>`` as a subprocess.

    Writes the PID to ``<exp>/.lock`` and starts a daemon thread that
    reads the subprocess's stdout into ``<exp>/run.log``. Returns the
    PID so the caller can stash it / kill it later.

    Optional keyword args mirror the same-named ``urika run`` flags so
    the dashboard's "+ New experiment" modal can pass through the form
    fields it already validates:

    * ``instructions`` → ``--instructions``
    * ``max_turns`` → ``--max-turns``
    * ``audience`` → ``--audience``
    * ``auto`` → ``--auto`` (autonomous, multi-experiment)
    * ``max_experiments`` → ``--max-experiments`` (only meaningful with auto)
    * ``review_criteria`` → ``--review-criteria``
    * ``resume`` → ``--resume`` (resume an interrupted run)

    Empty/None/False values are simply not appended to the command line.

    The subprocess receives ``URIKA_NO_TEE=1`` in its environment so
    that ``urika run`` skips its own ``OrchestratorLogger`` tee and
    we (the dashboard) remain the sole writer to ``run.log``.
    """
    exp_dir = project_path / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / "run.log"
    lock_path = exp_dir / ".lock"

    cmd = _python_cmd(executable) + [
        "run",
        project_name,
        "--experiment",
        experiment_id,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])
    if max_turns is not None:
        cmd.extend(["--max-turns", str(max_turns)])
    if audience:
        cmd.extend(["--audience", audience])
    if auto:
        cmd.append("--auto")
    if max_experiments is not None:
        cmd.extend(["--max-experiments", str(max_experiments)])
    if review_criteria:
        cmd.append("--review-criteria")
    if resume:
        cmd.append("--resume")

    env = _build_env(no_tee=True)

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
    draft: bool = False,
    executable: str | None = None,
) -> int:
    """Spawn ``urika finalize <project>`` as a subprocess.

    Writes the PID to ``<project>/projectbook/.finalize.lock`` and tees
    stdout to ``<project>/projectbook/finalize.log``. The lock is
    removed when the subprocess exits. Returns the PID.

    ``audience`` follows the finalize CLI allow-list
    (``{"novice", "standard", "expert"}``), which differs from the
    core/models.py ``VALID_AUDIENCES`` set; callers should validate
    against the CLI's set before invoking.

    When ``draft`` is True, ``--draft`` is appended so the finalizer
    writes interim outputs to ``projectbook/draft/`` instead of
    overwriting the final outputs.
    """
    book_dir = project_path / "projectbook"
    book_dir.mkdir(parents=True, exist_ok=True)
    log_path = book_dir / "finalize.log"
    lock_path = book_dir / ".finalize.lock"

    # Note: no ``--json`` flag here. ``--json`` would silence the
    # ``_make_on_message`` callback inside the CLI, suppressing the
    # tool-use prints that drive the SSE log stream's verbose output.
    # We don't parse the CLI's stdout — we tee it to a log file — so
    # text-mode output is fine.
    cmd = _python_cmd(executable) + [
        "finalize",
        project_name,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])
    if audience:
        cmd.extend(["--audience", audience])
    if draft:
        cmd.append("--draft")

    env = _build_env()

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


def spawn_report(
    project_name: str,
    project_path: Path,
    experiment_id: str,
    *,
    instructions: str = "",
    audience: str | None = None,
    executable: str | None = None,
) -> int:
    """Spawn ``urika report <project> --experiment <id>`` as a subprocess.

    Writes the PID to ``<exp>/.report.lock`` and tees stdout to
    ``<exp>/report.log``. The lock is removed when the subprocess
    exits. Returns the PID.

    ``audience`` follows the report CLI's allow-list
    (``{"novice", "standard", "expert"}``); callers should validate
    against the CLI's set before invoking.
    """
    exp_dir = project_path / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / "report.log"
    lock_path = exp_dir / ".report.lock"

    cmd = _python_cmd(executable) + [
        "report",
        project_name,
        "--experiment",
        experiment_id,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])
    if audience:
        cmd.extend(["--audience", audience])

    env = _build_env()

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


def spawn_evaluate(
    project_name: str,
    project_path: Path,
    experiment_id: str,
    *,
    instructions: str = "",
    executable: str | None = None,
) -> int:
    """Spawn ``urika evaluate <project> <experiment_id>`` as a subprocess.

    Writes the PID to ``<exp>/.evaluate.lock`` and tees stdout to
    ``<exp>/evaluate.log``. The lock is removed when the subprocess
    exits. Returns the PID.

    The evaluator does not produce a dedicated artifact file; it
    appends to ``progress.json`` and prints to stdout. The dashboard
    tails ``evaluate.log`` so the user can watch the agent's work.
    """
    exp_dir = project_path / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / "evaluate.log"
    lock_path = exp_dir / ".evaluate.lock"

    cmd = _python_cmd(executable) + [
        "evaluate",
        project_name,
        experiment_id,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])

    env = _build_env()

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


def spawn_summarize(
    project_name: str,
    project_path: Path,
    *,
    instructions: str = "",
    executable: str | None = None,
) -> int:
    """Spawn ``urika summarize <project>`` as a subprocess.

    Writes the PID to ``<project>/projectbook/.summarize.lock`` and tees
    stdout to ``<project>/projectbook/summarize.log``. The lock is
    removed when the subprocess exits. Returns the PID.

    The summarizer agent is read-only — its writable_dirs is empty.
    The ``urika summarize`` CLI handler itself writes the agent's
    final text output to ``projectbook/summary.md`` after the run
    completes; the dashboard relies on the presence of that file
    to flip the button label between "Summarize" and "Re-summarize".
    """
    book_dir = project_path / "projectbook"
    book_dir.mkdir(parents=True, exist_ok=True)
    log_path = book_dir / "summarize.log"
    lock_path = book_dir / ".summarize.lock"

    cmd = _python_cmd(executable) + [
        "summarize",
        project_name,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])

    env = _build_env()

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


def spawn_build_tool(
    project_name: str,
    project_path: Path,
    *,
    instructions: str,
    executable: str | None = None,
) -> int:
    """Spawn ``urika build-tool <project> <instructions>`` as a subprocess.

    Writes the PID to ``<project>/tools/.build.lock`` and tees stdout to
    ``<project>/tools/build.log``. The lock is removed when the
    subprocess exits. Returns the PID.

    ``instructions`` is a positional CLI argument (the tool description).
    It is required — callers must validate before reaching this helper;
    we still raise ``ValueError`` defensively to avoid spawning a CLI
    invocation that would block on the interactive prompt.
    """
    if not (instructions or "").strip():
        raise ValueError("instructions is required")
    tools_dir = project_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    log_path = tools_dir / "build.log"
    lock_path = tools_dir / ".build.lock"

    cmd = _python_cmd(executable) + [
        "build-tool",
        project_name,
        instructions,
    ]

    env = _build_env()

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


def spawn_present(
    project_name: str,
    project_path: Path,
    experiment_id: str,
    *,
    instructions: str = "",
    audience: str | None = None,
    executable: str | None = None,
) -> int:
    """Spawn ``urika present <project> --experiment <id>`` as a subprocess.

    Writes the PID to ``<exp>/.present.lock`` and tees stdout to
    ``<exp>/present.log``. The lock is removed when the subprocess
    exits. Returns the PID.

    The ``--experiment`` flag bypasses the present CLI's interactive
    prompt; the dashboard always supplies an explicit experiment ID
    (or the special tokens ``"project"`` / ``"all"``).
    """
    exp_dir = project_path / "experiments" / experiment_id
    exp_dir.mkdir(parents=True, exist_ok=True)
    log_path = exp_dir / "present.log"
    lock_path = exp_dir / ".present.lock"

    cmd = _python_cmd(executable) + [
        "present",
        project_name,
        "--experiment",
        experiment_id,
    ]
    if instructions:
        cmd.extend(["--instructions", instructions])
    if audience:
        cmd.extend(["--audience", audience])

    env = _build_env()

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
