"""Session-management slash commands — split out of repl/commands.py.

Holds /resume (continue a paused/stopped/failed experiment) and the
orchestrator-conversation lifecycle commands /resume-session and
/new-session.
"""

from __future__ import annotations

import click

from urika.repl.commands_registry import command
from urika.repl.helpers import _load_run_defaults, _prompt_numbered
from urika.repl.session import ReplSession


@command(
    "resume",
    requires_project=True,
    description="Resume a paused/stopped/failed experiment",
)
def cmd_resume(session: ReplSession, args: str) -> None:
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    experiments = list_experiments(session.project_path)
    resumable = []
    for exp in experiments:
        progress = load_progress(session.project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        if status in ("paused", "stopped", "failed"):
            resumable.append((exp, status))

    if not resumable:
        click.echo("  No paused, stopped, or failed experiments to resume.")
        return

    # If multiple, let user pick; if one or remote, use most recent directly
    if len(resumable) == 1 or session._is_remote_command:
        exp, status = resumable[-1]  # Most recent resumable
        click.echo(f"  Resuming {exp.experiment_id} [{status}]...")
    else:
        options = [f"{exp.experiment_id} [{status}]" for exp, status in resumable]
        choice = _prompt_numbered(
            "\n  Select experiment to resume:", options, default=1
        )
        exp_id = choice.split(" [")[0]
        click.echo(f"  Resuming {exp_id}...")
        # Find matching exp
        exp = next(e for e, _s in resumable if e.experiment_id == exp_id)

    import os

    from urika.repl import commands as _cmds_mod

    is_remote = session._is_remote_command

    os.environ["URIKA_REPL"] = "1"
    _cmds_mod._repl_session_ref = session
    session.set_agent_active("run")
    try:
        from urika.cli import run as cli_run

        ctx = click.Context(cli_run)
        defaults = _load_run_defaults(session)
        ctx.invoke(
            cli_run,
            project=session.project_name,
            experiment_id=exp.experiment_id,
            max_turns=defaults["max_turns"],
            resume=True,
            quiet=False,
            auto=(is_remote or defaults["auto_mode"] != "checkpoint"),
            instructions="",
            max_experiments=None,
        )
    finally:
        session.set_agent_idle()
        _cmds_mod._repl_session_ref = None
        os.environ.pop("URIKA_REPL", None)


@command(
    "resume-session",
    requires_project=True,
    description="Resume previous orchestrator session",
)
def cmd_resume_session(session: ReplSession, args: str) -> None:
    """Resume a previous orchestrator conversation."""
    from urika.core.orchestrator_sessions import list_sessions, load_session

    sessions = list_sessions(session.project_path)
    if not sessions:
        click.echo("  No saved sessions for this project.")
        return

    if not args:
        # Show numbered list
        click.echo()
        click.echo("  Recent sessions:")
        click.echo()
        for i, s in enumerate(sessions[:10]):
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(s["updated"]).strftime("%Y-%m-%d %H:%M")
            except Exception:
                dt = s.get("updated", "?")
            preview = (s.get("preview") or "(empty)")[:60]
            turns = s.get("turn_count", 0)
            click.echo(f"    {i + 1}. {dt} · {turns} turns")
            click.echo(f"       {preview}")
        click.echo()
        click.echo("  Type /resume-session <number> to resume.")
        click.echo()
        return

    # Resume by number
    try:
        num = int(args)
    except ValueError:
        click.echo(f"  Invalid number: {args}")
        return

    if num < 1 or num > len(sessions):
        click.echo("  Invalid session number. Use /resume-session to see the list.")
        return

    entry = sessions[num - 1]
    loaded = load_session(session.project_path, entry["session_id"])
    if not loaded:
        click.echo(f"  Session not found: {entry['session_id']}")
        return

    # Restore conversation to the orchestrator
    from urika.repl.main import _get_orchestrator

    orchestrator = _get_orchestrator(session)
    orchestrator.set_messages(loaded.recent_messages)
    session._orch_session = loaded

    turns = len(loaded.recent_messages) // 2
    click.echo(f"  Resumed session ({turns} turns)")


@command(
    "new-session",
    requires_project=True,
    description="Start a new orchestrator conversation",
)
def cmd_new_session(session: ReplSession, args: str) -> None:
    """Clear the orchestrator conversation and start fresh."""
    from urika.repl.main import _get_orchestrator

    orchestrator = _get_orchestrator(session)
    orchestrator.clear()
    session._orch_session = None
    click.echo("  Started a new session. Previous conversation archived.")
