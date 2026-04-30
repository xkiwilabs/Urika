"""Subprocess spawn helpers for browser-launched agent runs.

The dashboard kicks off CLI commands (``urika run``, ``urika finalize``,
``urika present``) as detached subprocesses whose stdout/stderr write
directly to a log file on disk; SSE log tailers read that file. Each
spawn writes a ``.lock`` file alongside its log; a daemon reaper thread
removes the lock when the subprocess exits, so SSE tailers can detect
completion.

The subprocess is started in a new session (``start_new_session=True``
on POSIX, ``CREATE_NEW_PROCESS_GROUP`` on Windows) and its stdout goes
straight to a file rather than through a pipe. That means a dashboard
restart (Ctrl+C → restart, or even SIGKILL of uvicorn) does not kill
running experiments: there is no pipe to receive SIGPIPE, and the child
is not in the dashboard's process group so terminal Ctrl+C does not
propagate to it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path


# Tracked only so tests can join/inspect the reaper thread; not used at runtime.
_DAEMON_THREADS: list[threading.Thread] = []


def _build_env(*, no_tee: bool = False) -> dict[str, str]:
    """Environment for spawned urika subprocesses.

    Always sets ``PYTHONUNBUFFERED=1`` so the child writes line-by-line
    to its log file (block buffering on stdout would otherwise hold
    output in 8KB chunks until process exit, which would defeat the
    SSE log tailer). When ``no_tee=True`` also sets ``URIKA_NO_TEE`` so
    ``urika run`` skips its own log tee — the dashboard-spawned child
    becomes the sole writer.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if no_tee:
        env["URIKA_NO_TEE"] = "1"
    return env


def _python_cmd(executable: str | None) -> list[str]:
    """Base command for spawning ``python -u -m urika ...``.

    The ``-u`` flag disables Python's stdout/stderr buffering in the
    child so output streams line-by-line into the log file instead of
    being held in 8KB blocks until process exit.
    """
    return [executable or sys.executable, "-u", "-m", "urika"]


def _spawn_detached(
    cmd: list[str],
    env: dict[str, str],
    log_path: Path,
    lock_path: Path,
) -> int:
    """Start a subprocess that survives dashboard restart.

    - ``stdout`` and ``stderr`` go straight to ``log_path`` (no pipe
      through the dashboard process), so SIGPIPE on dashboard exit
      can't kill the child.
    - On POSIX, ``start_new_session=True`` puts the child in a new
      session, so it isn't in the dashboard's process group — Ctrl+C
      in the dashboard's terminal doesn't propagate to the child. On
      Windows, ``CREATE_NEW_PROCESS_GROUP`` provides the equivalent
      isolation from console signals.
    - The drainer thread is gone — the child writes directly. SSE
      tailers read ``log_path`` from disk; that contract is unchanged.
    - The PID is written to ``lock_path`` exactly as before. A small
      reaper thread watches the child and removes ``lock_path`` when
      the child exits (so SSE tailers can detect completion).

    Limitation: if the dashboard process is hard-killed (SIGKILL)
    while a child is still running, the reaper thread dies with it
    and the lock file remains until the user manually clears it via
    the "Clear stale" UI (which uses ``_is_active_run_lock`` to
    detect dead PIDs). The child itself keeps running uninterrupted.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fd = open(log_path, "ab", buffering=0)  # append, unbuffered
    try:
        popen_kwargs: dict = {
            "stdout": log_fd,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "env": env,
            "close_fds": True,
        }
        if sys.platform == "win32":
            # Windows has no sessions; CREATE_NEW_PROCESS_GROUP gives the
            # equivalent isolation from console Ctrl+C / Ctrl+Break.
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **popen_kwargs)
    finally:
        # Parent doesn't need the FD any more — the child has its own copy.
        log_fd.close()

    lock_path.write_text(str(proc.pid), encoding="utf-8")
    _start_reaper(proc, lock_path)
    return proc.pid


def _start_reaper(proc: subprocess.Popen, lock_path: Path) -> threading.Thread:
    """Daemon thread that waits for the child to exit and removes the lock.

    Replaces the old ``_start_drainer`` for detached spawns — we no
    longer need to forward stdout (the child writes directly to the
    log file), only to detect exit so the lock comes off. If the
    dashboard restarts while the child is still running, the new
    dashboard's ``list_active_operations`` correctly sees the live
    PID and reports it. When the child eventually exits, this
    dashboard's reaper (or, if the dashboard has already restarted,
    the user's manual "Clear stale" action) cleans up the lock.

    When the child exits with a non-zero return code AND the lock
    path matches an experiment ``.lock`` (i.e. ``<exp>/.lock``), the
    reaper writes ``progress.json["status"] = "stopped"`` (or
    ``"failed"``) before unlinking the lock. This is a fallback for
    when the CLI's signal handler couldn't write the session state
    (e.g. SIGKILL, or pre-v0.3.2 binaries that only handled SIGINT)
    — without it the dashboard experiment card falls back to the
    static ``"pending"`` from ``experiment.json`` and the user can't
    tell the run was stopped vs. never started.
    """
    import logging

    logger = logging.getLogger(__name__)

    def _wait() -> None:
        returncode = None
        try:
            returncode = proc.wait()
        except Exception as exc:
            # Daemon-thread exception would otherwise die silently and
            # leave the lock forever — a "ghost run" the user has to
            # clear by hand from the UI.
            logger.warning(
                "Reaper thread for %s crashed: %s", lock_path, exc, exc_info=True
            )
        finally:
            try:
                _write_terminal_status_if_needed(lock_path, returncode)
            except Exception as exc:
                logger.warning(
                    "Reaper terminal-status write failed for %s: %s",
                    lock_path,
                    exc,
                    exc_info=True,
                )
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    _DAEMON_THREADS.append(t)
    return t


def _write_terminal_status_if_needed(
    lock_path: Path, returncode: int | None
) -> None:
    """Write a ``stopped`` / ``failed`` status fallback for a stopped run.

    Called from :func:`_start_reaper` when an experiment lock's child
    process exits. If the child exited cleanly (returncode 0) the CLI's
    own teardown already wrote a ``completed`` status — do nothing.
    If the child exited with a non-zero code (signal, crash) the CLI
    may have written ``stopped`` itself via its SIGTERM handler — but
    if it didn't (SIGKILL, hard crash before the handler ran), we
    write ``stopped`` here so the dashboard card flips off ``pending``.

    Only acts on experiment-level locks (``<exp_dir>/.lock``); other
    locks (``.advisor.lock`` etc.) don't have ``progress.json`` and
    are skipped.
    """
    if returncode is None or returncode == 0:
        return
    if lock_path.name != ".lock":
        return
    exp_dir = lock_path.parent
    if not exp_dir.is_dir() or exp_dir.parent.name != "experiments":
        return

    progress_path = exp_dir / "progress.json"
    if not progress_path.exists():
        return

    try:
        from urika.core.progress import load_progress, update_experiment_status
    except ImportError:
        return

    try:
        progress = load_progress(exp_dir.parent.parent, exp_dir.name)
    except Exception:
        return

    current = (progress or {}).get("status") or ""
    # If the CLI's signal handler already wrote a terminal status,
    # respect it. Only fill in when the status is missing or still in
    # a non-terminal state (running / pending / starting).
    if current in ("stopped", "failed", "completed"):
        return

    new_status = "stopped" if returncode in (-15, -2, 130, 143) else "failed"
    try:
        update_experiment_status(
            exp_dir.parent.parent,
            exp_dir.name,
            new_status,
        )
    except Exception:
        # Best-effort — never let a status write block lock cleanup.
        pass


def _start_drainer(
    proc: subprocess.Popen, log_path: Path, lock_path: Path
) -> threading.Thread:
    """Legacy: drain ``proc.stdout`` to ``log_path`` and remove the lock on exit.

    Kept for backward compatibility with any external caller / test
    that still uses the piped-stdout shape. The spawn helpers in this
    module no longer call it — they use ``_spawn_detached`` instead,
    which writes the child's stdout directly to the log file so the
    child can survive dashboard restart.
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
    advisor_first: bool = False,
    executable: str | None = None,
) -> int:
    """Spawn ``urika run <project> --experiment <exp_id>`` as a subprocess.

    Writes the PID to ``<exp>/.lock`` and detaches the subprocess so
    that its stdout/stderr go directly to ``<exp>/run.log``. Returns
    the PID so the caller can stash it / kill it later.

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
    * ``advisor_first`` → ``--advisor-first`` (run the advisor before the
      orchestrator loop so the user sees its output stream in run.log
      alongside the other agents)

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
    if advisor_first:
        cmd.append("--advisor-first")

    env = _build_env(no_tee=True)
    return _spawn_detached(cmd, env, log_path, lock_path)


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

    Writes the PID to ``<project>/projectbook/.finalize.lock`` and
    detaches the subprocess so its stdout/stderr go directly to
    ``<project>/projectbook/finalize.log``. The lock is removed when
    the subprocess exits. Returns the PID.

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
    return _spawn_detached(cmd, env, log_path, lock_path)


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

    Writes the PID to ``<exp>/.report.lock`` and detaches the
    subprocess so its stdout/stderr go directly to ``<exp>/report.log``.
    The lock is removed when the subprocess exits. Returns the PID.

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
    return _spawn_detached(cmd, env, log_path, lock_path)


def spawn_evaluate(
    project_name: str,
    project_path: Path,
    experiment_id: str,
    *,
    instructions: str = "",
    executable: str | None = None,
) -> int:
    """Spawn ``urika evaluate <project> <experiment_id>`` as a subprocess.

    Writes the PID to ``<exp>/.evaluate.lock`` and detaches the
    subprocess so its stdout/stderr go directly to
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
    return _spawn_detached(cmd, env, log_path, lock_path)


def spawn_summarize(
    project_name: str,
    project_path: Path,
    *,
    instructions: str = "",
    executable: str | None = None,
) -> int:
    """Spawn ``urika summarize <project>`` as a subprocess.

    Writes the PID to ``<project>/projectbook/.summarize.lock`` and
    detaches the subprocess so its stdout/stderr go directly to
    ``<project>/projectbook/summarize.log``. The lock is removed when
    the subprocess exits. Returns the PID.

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
    return _spawn_detached(cmd, env, log_path, lock_path)


def spawn_advisor(
    project_name: str,
    project_path: Path,
    question: str,
    *,
    executable: str | None = None,
) -> int:
    """Spawn ``urika advisor <project> <question>`` as a subprocess.

    Writes the PID to ``<project>/projectbook/.advisor.lock`` and
    detaches the subprocess so its stdout/stderr go directly to
    ``<project>/projectbook/advisor.log``. The lock is removed when
    the subprocess exits. Returns the PID.

    The CLI's ``urika advisor`` command takes the question as a
    positional argument; passing it explicitly skips the interactive
    prompt fallback so the subprocess never blocks waiting on stdin.
    The CLI itself appends the user message + advisor reply to
    ``projectbook/advisor-history.json`` via ``append_exchange`` after
    the run completes — the dashboard's ``/advisor`` page picks up the
    new entries on next render. The dashboard does NOT need to write
    history itself.

    ``question`` is required — callers must validate before reaching
    this helper; we still raise ``ValueError`` defensively to avoid
    spawning a CLI invocation that would block on the interactive
    prompt.
    """
    if not (question or "").strip():
        raise ValueError("question is required")
    book_dir = project_path / "projectbook"
    book_dir.mkdir(parents=True, exist_ok=True)
    log_path = book_dir / "advisor.log"
    lock_path = book_dir / ".advisor.lock"

    cmd = _python_cmd(executable) + [
        "advisor",
        project_name,
        question,
    ]

    env = _build_env()
    return _spawn_detached(cmd, env, log_path, lock_path)


def spawn_build_tool(
    project_name: str,
    project_path: Path,
    *,
    instructions: str,
    executable: str | None = None,
) -> int:
    """Spawn ``urika build-tool <project> <instructions>`` as a subprocess.

    Writes the PID to ``<project>/tools/.build.lock`` and detaches the
    subprocess so its stdout/stderr go directly to
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
    return _spawn_detached(cmd, env, log_path, lock_path)


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

    Writes the PID to ``<exp>/.present.lock`` and detaches the
    subprocess so its stdout/stderr go directly to
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
    return _spawn_detached(cmd, env, log_path, lock_path)
