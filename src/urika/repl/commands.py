"""Slash command handlers for the REPL."""

from __future__ import annotations
import click
from urika.cli_display import _C
from urika.repl.session import ReplSession

# ── Imported helpers (re-exported for backward compat) ──
from urika.repl.helpers import (  # noqa: F401
    _pick_experiment,
    _run_single_agent,
    _save_presentation,
    _get_audience,
    _file_link,
    _fmt_tokens,
    _prompt_numbered,
    _load_run_defaults,
    get_global_stats,
    get_all_commands,
    get_command_names,
    get_project_names,
    get_experiment_ids,
)

# ── Imported agent command functions ──
from urika.repl.cmd_agents import (  # noqa: F401
    cmd_advisor,
    cmd_evaluate,
    cmd_plan,
    cmd_report,
    cmd_present,
    cmd_finalize,
    cmd_build_tool,
)


# Registry of commands — re-exported from commands_registry so external
# callers (helpers, TUI) can keep importing them from this module.
from urika.repl.commands_registry import (  # noqa: E402
    GLOBAL_COMMANDS,
    PROJECT_COMMANDS,
    command,
)

# Module-level callback for passing queued user input into the orchestrator.
# Set before invoking the CLI run command from the REPL, cleared after.
_user_input_callback = None

# Module-level ref to the REPL session so cli.py can access the persistent bus.
_repl_session_ref: ReplSession | None = None


def _get_repl_bus():
    """Return the REPL session's notification bus, or None."""
    if _repl_session_ref is not None:
        return _repl_session_ref.notification_bus
    return None


def _get_repl_session():
    """Return the active REPL session, or None."""
    return _repl_session_ref


def _format_relative(delta) -> str:
    """Render a timedelta as 'just now', '5 minutes ago', '3 hours ago', '2 days ago', etc."""
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = seconds // 86400
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


# ── Global commands ─────────────────────────────────────────


@command("help", description="Show available commands")
def cmd_help(session: ReplSession, args: str) -> None:

    click.echo(f"\n  {_C.BOLD}Commands:{_C.RESET}")
    for name, entry in sorted(GLOBAL_COMMANDS.items()):
        click.echo(f"    /{name:<16s} {entry['description']}")
    if session.has_project:
        for name, entry in sorted(PROJECT_COMMANDS.items()):
            click.echo(f"    /{name:<16s} {entry['description']}")
    click.echo()


@command("list", description="List all projects")
def cmd_list(session: ReplSession, args: str) -> None:
    from urika.core.registry import ProjectRegistry

    registry = ProjectRegistry()
    projects = registry.list_all()
    if not projects:
        click.echo("  No projects registered.")
        return
    click.echo()
    for name, path in projects.items():
        marker = " \u25c6" if session.project_name == name else "  "
        click.echo(f"  {marker} {name}")
    click.echo()


@command("project", description="Load a project")
def cmd_project(session: ReplSession, args: str) -> None:
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import load_project_config
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress
    from urika.cli_display import print_success

    name = args.strip()
    if not name:
        click.echo("  Usage: /project <name>")
        return

    registry = ProjectRegistry()
    path = registry.get(name)
    if path is None:
        click.echo(f"  Project '{name}' not found.")
        return

    if session.has_project:
        session.save_usage()

    # Stop old notification bus if switching projects
    if session.notification_bus is not None:
        try:
            session.notification_bus.stop()
        except Exception:
            pass
        session.notification_bus = None

    try:
        config = load_project_config(path)
    except FileNotFoundError:
        click.echo(f"  Project directory missing: {path}")
        return

    session.load_project(path, name)

    # Sync chat orchestrator to new project (if active)
    from urika.repl.main import _orchestrator

    if _orchestrator is not None:
        _orchestrator.set_project(path)

    # Start notification bus for this project
    try:
        from urika.notifications import build_bus

        bus = build_bus(path)
        if bus is not None:
            bus.start(session=session)
            session.notification_bus = bus
    except Exception:
        pass  # Notifications are best-effort

    experiments = list_experiments(path)
    completed = sum(
        1
        for e in experiments
        if load_progress(path, e.experiment_id).get("status") == "completed"
    )

    # Show privacy mode and notifications
    import tomllib

    toml_path = path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tdata = tomllib.load(f)
            privacy = tdata.get("privacy", {}).get("mode", "open")
            notif_channels = tdata.get("notifications", {}).get("channels", [])
            notif_str = ", ".join(notif_channels) if notif_channels else "off"
        except Exception:
            privacy = "open"
            notif_str = "off"
    else:
        privacy = "open"
        notif_str = "off"

    click.echo()
    print_success(f"Project: {name} \u00b7 {config.mode}")
    click.echo(f"    {len(experiments)} experiments \u00b7 {completed} completed")
    click.echo(f"    Privacy: {privacy} \u00b7 Notifications: {notif_str}")

    # Check private endpoint reachability for hybrid/private mode
    from urika.core.privacy import check_private_endpoint, requires_private_endpoint

    if requires_private_endpoint(session.project_path):
        reachable, msg = check_private_endpoint(session.project_path)
        if reachable:
            click.echo(f"    Local model: {msg}")
            session._private_endpoint_ok = True
        else:
            click.echo(f"    \u2717 {msg}")
            click.echo(
                "    Agent commands disabled. Start your local model or switch to open: /config"
            )
            session._private_endpoint_ok = False
    else:
        session._private_endpoint_ok = True  # open mode, no restriction

    # After project is loaded, check for recent sessions
    try:
        from urika.core.orchestrator_sessions import get_most_recent

        recent = get_most_recent(session.project_path)
        if recent:
            from datetime import datetime, timezone

            # Relative time string
            try:
                updated_dt = datetime.fromisoformat(
                    recent.updated.replace("Z", "+00:00")
                )
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                relative = _format_relative(now - updated_dt)
            except Exception:
                relative = recent.updated

            # Preview snippet
            preview = (recent.preview or "").strip()
            if preview:
                preview_short = preview[:60]
                if len(preview) > 60:
                    preview_short = preview_short.rsplit(" ", 1)[0] + "…"
                click.echo(
                    f'  Previous session from {relative}: "{preview_short}"'
                )
                click.echo("  Type /resume-session to continue.")
            else:
                click.echo(
                    f"  Previous session from {relative} available. "
                    "Type /resume-session to continue."
                )
    except Exception:
        pass

    click.echo()


@command("new", description="Create a new project")
def cmd_new(session: ReplSession, args: str) -> None:
    import os as _os

    from urika.cli import _sanitize_project_name, new as cli_new
    from urika.core.registry import ProjectRegistry

    name = args.strip() if args.strip() else None
    if name is not None:
        name = _sanitize_project_name(name)

    # Snapshot existing projects so we can detect a new one
    registry = ProjectRegistry()
    before = set(registry.list_all().keys())

    _os.environ["URIKA_REPL"] = "1"
    ctx = click.Context(cli_new)
    try:
        ctx.invoke(
            cli_new,
            name=name,
            question=None,
            mode=None,
            data_path=None,
            description=None,
        )
    except (SystemExit, EOFError, KeyboardInterrupt):
        pass
    except Exception as exc:
        click.echo(f"  Error during project creation: {exc}")
    finally:
        _os.environ.pop("URIKA_REPL", None)

    # Auto-load the newly created project (only if one was actually created)
    registry = ProjectRegistry()
    after = registry.list_all()
    new_projects = set(after.keys()) - before
    if new_projects:
        new_name = new_projects.pop()
        session.load_project(after[new_name], new_name)
        click.echo(f"  Loaded project: {new_name}")


@command("delete", description="Move a project to trash and unregister it")
def cmd_delete(session: ReplSession, args: str) -> None:
    from urika.core.project_delete import (
        ActiveRunError,
        ProjectNotFoundError,
        trash_project,
    )

    name = args.strip()
    if not name:
        click.echo("  Usage: /delete <name>")
        return

    try:
        click.confirm(
            f"  Move project '{name}' to ~/.urika/trash/? "
            "(files preserved, registry entry removed)",
            abort=True,
        )
    except click.Abort:
        click.echo("  Aborted.")
        return

    try:
        result = trash_project(name)
    except ProjectNotFoundError:
        click.echo(f"  Project '{name}' is not registered.")
        return
    except ActiveRunError as exc:
        click.echo(f"  {exc}")
        return

    if result.registry_only:
        click.echo(
            f"  Unregistered '{name}' "
            f"(folder at {result.original_path} was already missing)."
        )
    else:
        click.echo(f"  Moved '{name}' to {result.trash_path}")

    if session.project_name == name:
        # User deleted the project they were working in — clear context so
        # subsequent commands don't try to read a now-trashed directory.
        if session.notification_bus is not None:
            try:
                session.notification_bus.stop()
            except Exception:
                pass
            session.notification_bus = None
        session.clear_project()
        click.echo("  Project context cleared. Use /list to pick another.")


@command("quit", description="Exit Urika")
def cmd_quit(session: ReplSession, args: str) -> None:
    session.save_usage()
    raise SystemExit(0)


@command("copy", description="Copy the last N output lines to the clipboard")
def cmd_copy(session: ReplSession, args: str) -> None:
    """Clipboard fallback for terminals that don't forward Shift+drag.

    Usage:
        /copy        copy the last 40 output lines
        /copy 100    copy the last 100 output lines
    """
    from urika.cli_display import print_error, print_success, print_warning

    arg = args.strip()
    if arg:
        try:
            n = int(arg)
        except ValueError:
            print_error("Usage: /copy [N]  — copies the last N output lines (default 40).")
            return
        if n <= 0:
            print_error("N must be a positive integer.")
            return
    else:
        n = 40

    lines = session.recent_output_lines[-n:]
    if not lines:
        print_warning("No output to copy yet.")
        return

    text = "\n".join(lines)
    try:
        import pyperclip

        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        # Happens on headless Linux without xclip/xsel. Don't crash — tell
        # the user what to install and fall back to printing the text.
        print_error(
            f"Clipboard copy failed ({exc}). On Linux, install xclip or "
            "xsel. The text is printed below so you can copy it manually:"
        )
        print(text)
        return
    except Exception as exc:
        print_error(f"Clipboard copy failed: {exc}")
        return

    print_success(f"Copied last {len(lines)} output lines ({len(text)} chars) to clipboard.")


@command("config", description="Configure privacy mode and models")
def cmd_config(session: ReplSession, args: str) -> None:
    from urika.cli import config_command

    arg = args.strip().lstrip("-")
    ctx = click.Context(config_command)

    if arg == "show":
        # Show project config if project loaded, else global
        ctx.invoke(
            config_command,
            project=session.project_name if session.has_project else None,
            show=True,
            json_output=False,
        )
    elif arg == "global":
        # Force global config
        ctx.invoke(
            config_command,
            project=None,
            show=False,
            json_output=False,
        )
    elif arg == "global show":
        ctx.invoke(
            config_command,
            project=None,
            show=True,
            json_output=False,
        )
    else:
        # Default: configure current project if loaded, else global
        ctx.invoke(
            config_command,
            project=session.project_name if session.has_project else None,
            show=False,
            json_output=False,
        )


@command("notifications", description="Configure notification channels")
def cmd_notifications(session: ReplSession, args: str) -> None:
    from urika.cli import notifications_command

    arg = args.strip().lstrip("-")
    ctx = click.Context(notifications_command)

    project = session.project_name if session.has_project else None

    if arg == "show":
        ctx.invoke(
            notifications_command,
            show=True,
            send_test=False,
            disable=False,
            project=project,
        )
    elif arg == "test":
        ctx.invoke(
            notifications_command,
            show=False,
            send_test=True,
            disable=False,
            project=project,
        )
    elif arg == "disable":
        ctx.invoke(
            notifications_command,
            show=False,
            send_test=False,
            disable=True,
            project=project,
        )
    else:
        ctx.invoke(
            notifications_command,
            show=False,
            send_test=False,
            disable=False,
            project=project,
        )


@command("setup", description="Run the first-time setup wizard")
def cmd_setup(session: ReplSession, args: str) -> None:
    """Forward to the ``urika setup`` Click command.

    Pre-v0.4.2 ``"setup"`` was listed in the TUI's ``_WORKER_COMMANDS``
    set but had no slash handler — typing ``/setup`` printed
    "Unknown command" and a new TUI user could not run setup without
    dropping to a shell. Closes C7.
    """
    from urika.cli import setup_command

    ctx = click.Context(setup_command)
    ctx.invoke(setup_command)


@command("summarize", description="Generate a project summary")
def cmd_summarize(session: ReplSession, args: str) -> None:
    """Forward to the ``urika summarize`` Click command. Closes H8."""
    from urika.cli import summarize as summarize_command

    project = session.project_name if session.has_project else None
    instructions = args.strip() or None

    ctx = click.Context(summarize_command)
    ctx.invoke(
        summarize_command,
        project=project,
        instructions=instructions,
        json_output=False,
    )


@command("sessions", description="List or export orchestrator sessions")
def cmd_sessions(session: ReplSession, args: str) -> None:
    """Dispatch to ``urika sessions list|export``. Closes H8.

    Usage from the TUI:

        /sessions               → list sessions for the loaded project
        /sessions list          → same as above
        /sessions export <id>   → export a session as Markdown
    """
    from urika.cli import sessions as sessions_module

    project = session.project_name if session.has_project else None
    if project is None:
        click.echo("No project loaded. Use /project <name> first.")
        return

    parts = args.strip().split()
    sub = (parts[0] if parts else "list").lower()

    if sub in ("", "list"):
        ctx = click.Context(sessions_module.sessions_list)
        ctx.invoke(sessions_module.sessions_list, project=project, json_output=False)
        return

    if sub == "export":
        if len(parts) < 2:
            click.echo("Usage: /sessions export <session-id>")
            return
        session_id = parts[1]
        ctx = click.Context(sessions_module.sessions_export)
        ctx.invoke(
            sessions_module.sessions_export,
            project=project,
            session_id=session_id,
            fmt="md",
            output=None,
        )
        return

    click.echo(f"Unknown sessions subcommand: {sub!r}. Try /sessions list or /sessions export <id>.")


@command("memory", description="Project memory: list, show, add, delete")
def cmd_memory(session: ReplSession, args: str) -> None:
    """Dispatch to the ``urika memory`` group. Closes H8.

    Usage from the TUI:

        /memory                  → list entries
        /memory list             → same
        /memory show <topic>     → print one entry
        /memory delete <file>    → trash an entry (with confirm)

    ``/memory add`` is intentionally NOT exposed here because the
    underlying CLI variant opens an editor (``click.edit``) which
    won't reach the TUI bridge. Use ``urika memory add`` from a
    shell for now.
    """
    from urika.cli.memory import memory_list, memory_show, memory_delete

    project = session.project_name if session.has_project else None
    if project is None:
        click.echo("No project loaded. Use /project <name> first.")
        return

    parts = args.strip().split()
    sub = (parts[0] if parts else "list").lower()

    if sub in ("", "list"):
        ctx = click.Context(memory_list)
        ctx.invoke(memory_list, project=project, json_output=False)
        return

    if sub == "show":
        if len(parts) < 2:
            click.echo("Usage: /memory show <topic>")
            return
        ctx = click.Context(memory_show)
        ctx.invoke(memory_show, project=project, topic=parts[1])
        return

    if sub == "delete":
        if len(parts) < 2:
            click.echo("Usage: /memory delete <filename>")
            return
        ctx = click.Context(memory_delete)
        ctx.invoke(memory_delete, project=project, filename=parts[1], force=False)
        return

    click.echo(
        f"Unknown memory subcommand: {sub!r}. "
        f"Try /memory list, /memory show <topic>, or /memory delete <file>."
    )


@command("venv", description="Project venv: create or status")
def cmd_venv(session: ReplSession, args: str) -> None:
    """Dispatch to ``urika venv create|status``. Closes H8."""
    from urika.cli import venv_create, venv_status

    project = session.project_name if session.has_project else None
    if project is None:
        click.echo("No project loaded. Use /project <name> first.")
        return

    parts = args.strip().split()
    sub = (parts[0] if parts else "status").lower()

    if sub == "create":
        ctx = click.Context(venv_create)
        ctx.invoke(venv_create, project=project)
        return
    if sub in ("", "status"):
        ctx = click.Context(venv_status)
        ctx.invoke(venv_status, project=project)
        return

    click.echo(f"Unknown venv subcommand: {sub!r}. Try /venv create or /venv status.")


@command(
    "experiment-create",
    description="Create a new experiment in the loaded project",
    requires_project=True,
)
def cmd_experiment_create(session: ReplSession, args: str) -> None:
    """Create a new experiment. Closes H8.

    Usage:

        /experiment-create <name> [hypothesis...]

    If no hypothesis is supplied the experiment is created with an
    empty hypothesis (the planning agent will fill it in on the
    first ``/run``).
    """
    from urika.cli import experiment_create

    parts = args.strip().split(maxsplit=1)
    if not parts:
        click.echo("Usage: /experiment-create <name> [hypothesis...]")
        return
    exp_name = parts[0]
    hypothesis = parts[1] if len(parts) > 1 else ""

    ctx = click.Context(experiment_create)
    ctx.invoke(
        experiment_create,
        project=session.project_name,
        name=exp_name,
        hypothesis=hypothesis,
    )


@command("usage", description="Show usage stats")
def cmd_usage(session: ReplSession, args: str) -> None:
    from urika.cli_display import _format_duration
    from urika.core.usage import format_usage, get_last_session, get_totals

    # Check if on subscription (SDK cost returns None)
    is_sub = session.total_cost_usd == 0 and session.agent_calls > 0

    if session.has_project:
        click.echo(f"\n  {_C.BOLD}Usage: {session.project_name}{_C.RESET}")

        # Current session
        elapsed = _format_duration(session.elapsed_ms)
        tokens = session.total_tokens_in + session.total_tokens_out
        cost_str = f"~${session.total_cost_usd:.2f}"
        if is_sub:
            cost_str += " (estimated \u2014 plan user)"
        click.echo(
            f"  This session: {elapsed} \u00b7 {_fmt_tokens(tokens)} tokens \u00b7 "
            f"{cost_str} \u00b7 {session.agent_calls} agent calls"
        )

        # Historical
        last = get_last_session(session.project_path)
        totals = get_totals(session.project_path)
        if totals.get("sessions", 0) > 0:
            click.echo(format_usage(last, totals, is_subscription=is_sub))
    else:
        # Show usage across all projects
        from urika.core.registry import ProjectRegistry

        registry = ProjectRegistry()
        projects = registry.list_all()
        if not projects:
            click.echo("  No projects.")
            return

        click.echo(f"\n  {_C.BOLD}Usage across all projects:{_C.RESET}")
        grand_tokens = 0
        grand_cost = 0.0
        grand_calls = 0
        grand_sessions = 0
        for name, path in projects.items():
            totals = get_totals(path)
            if totals.get("sessions", 0) > 0:
                tokens = totals.get("total_tokens_in", 0) + totals.get(
                    "total_tokens_out", 0
                )
                click.echo(
                    f"  {name}: {totals['sessions']} sessions \u00b7 "
                    f"{_fmt_tokens(tokens)} tokens \u00b7 "
                    f"~${totals['total_cost_usd']:.2f}"
                )
                grand_tokens += tokens
                grand_cost += totals["total_cost_usd"]
                grand_calls += totals["total_agent_calls"]
                grand_sessions += totals["sessions"]
        if grand_sessions > 0:
            click.echo(
                f"\n  {_C.BOLD}Total: {grand_sessions} sessions \u00b7 "
                f"{_fmt_tokens(grand_tokens)} tokens \u00b7 "
                f"~${grand_cost:.2f} \u00b7 {grand_calls} agent calls{_C.RESET}"
            )
    click.echo()


@command("tools", description="List available tools")
def cmd_tools(session: ReplSession, args: str) -> None:
    from urika.tools import ToolRegistry

    registry = ToolRegistry()
    registry.discover()

    # Also discover project-specific tools if a project is loaded
    if session.has_project:
        registry.discover_project(session.project_path / "tools")

    names = registry.list_all()
    if not names:
        click.echo("  No tools found.")
        return
    click.echo()
    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"    {tool.name()}  [{tool.category()}]  {tool.description()}")
    click.echo()


@command("stop", description="Stop the running agent/experiment")
def cmd_stop(session: ReplSession, args: str) -> None:
    """Stop the currently running agent or experiment immediately."""
    if not session.agent_running and not session.agent_active:
        click.echo("  No agent is currently running.")
        return

    # Write stop flag for run_experiment's PauseController
    if session.project_path:
        flag = session.project_path / ".urika" / "pause_requested"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("stop", encoding="utf-8")

    active = session.agent_name or session.active_command or "command"
    session.set_agent_idle()
    click.echo(f"  Stopped /{active}.")


@command("pause", requires_project=True, description="Pause experiment after current subagent")
def cmd_pause(session: ReplSession, args: str) -> None:
    """Pause the running experiment after the current subagent finishes."""
    if not session.agent_active:
        click.echo("  No agent is currently running.")
        return

    if session.project_path:
        flag = session.project_path / ".urika" / "pause_requested"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("pause", encoding="utf-8")

    click.echo("  Pausing after current subagent finishes...")
    click.echo("  Type /resume to continue.")


# ── Project-specific commands ───────────────────────────────


@command("status", requires_project=True, description="Show project status")
def cmd_status(session: ReplSession, args: str) -> None:
    from urika.cli import status as cli_status

    # Call the existing status function
    ctx = click.Context(cli_status)
    ctx.invoke(cli_status, name=session.project_name)



@command("experiments", requires_project=True, description="List experiments")
def cmd_experiments(session: ReplSession, args: str) -> None:
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No experiments yet.")
        return
    click.echo()
    for exp in experiments:
        progress = load_progress(session.project_path, exp.experiment_id)
        runs = progress.get("runs", [])
        status = progress.get("status", "pending")
        click.echo(f"    {exp.experiment_id}  [{status}, {len(runs)} runs]")
    click.echo()


@command(
    "delete-experiment",
    requires_project=True,
    description="Move an experiment to project-local trash",
)
def cmd_delete_experiment(session: ReplSession, args: str) -> None:
    from urika.core.experiment_delete import (
        ActiveExperimentError,
        ExperimentNotFoundError,
        trash_experiment,
    )

    exp_id = args.strip()
    if not exp_id:
        click.echo("  Usage: /delete-experiment <exp_id>")
        return

    try:
        click.confirm(
            f"  Move experiment '{exp_id}' to "
            f"{session.project_path}/trash/? "
            "(files preserved, experiment dir removed)",
            abort=True,
        )
    except click.Abort:
        click.echo("  Aborted.")
        return

    try:
        result = trash_experiment(
            session.project_path, session.project_name, exp_id
        )
    except ExperimentNotFoundError:
        click.echo(f"  Experiment '{exp_id}' not found.")
        return
    except ActiveExperimentError as exc:
        click.echo(f"  {exc}")
        return

    click.echo(f"  Moved '{exp_id}' to {result.trash_path}")


@command("methods", requires_project=True, description="Show methods table")
def cmd_methods(session: ReplSession, args: str) -> None:
    from urika.core.method_registry import load_methods

    methods = load_methods(session.project_path)
    if not methods:
        click.echo("  No methods yet.")
        return
    click.echo()
    for m in methods:
        metrics = m.get("metrics", {})
        nums = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        metric_str = ", ".join(f"{k}={v}" for k, v in list(nums.items())[:2])
        click.echo(f"    {m['name']}  [{m.get('status', '')}]  {metric_str}")
    click.echo()


@command(
    "results", requires_project=True, description="Show project results/leaderboard"
)
def cmd_results(session: ReplSession, args: str) -> None:
    from urika.evaluation.leaderboard import load_leaderboard
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    # Parse optional experiment filter from args
    experiment_filter = args.strip() if args else ""

    leaderboard = load_leaderboard(session.project_path)
    ranking = leaderboard.get("ranking", [])

    if ranking and not experiment_filter:
        click.echo(f"\n  {_C.BOLD}Leaderboard:{_C.RESET}")
        for entry in ranking:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in entry.get("metrics", {}).items()
            )
            click.echo(f"    #{entry['rank']}  {entry['method']}  {metrics_str}")
        click.echo()
        return

    # No leaderboard or specific experiment requested — show runs
    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No results yet.")
        return

    if experiment_filter:
        matched = [e for e in experiments if e.experiment_id == experiment_filter]
        if not matched:
            click.echo(f"  Experiment '{experiment_filter}' not found.")
            return
        exp = matched[0]
    else:
        exp = experiments[-1]
    progress = load_progress(session.project_path, exp.experiment_id)
    runs = progress.get("runs", [])
    if not runs:
        click.echo("  No results yet.")
        return

    click.echo(f"\n  {_C.BOLD}Runs for {exp.experiment_id}:{_C.RESET}")
    for run in runs:
        metrics_str = ", ".join(f"{k}={v}" for k, v in run.get("metrics", {}).items())
        click.echo(f"    {run['run_id']}  {run['method']}  {metrics_str}")
    click.echo()



@command("criteria", requires_project=True, description="Show current criteria")
def cmd_criteria(session: ReplSession, args: str) -> None:
    from urika.core.criteria import load_criteria

    c = load_criteria(session.project_path)
    if c is None:
        click.echo("  No criteria set.")
        return
    click.echo(f"\n  Criteria v{c.version} (set by {c.set_by})")
    click.echo(f"  Type: {c.criteria.get('type', 'unknown')}")
    threshold = c.criteria.get("threshold", {})
    primary = threshold.get("primary", {})
    if primary:
        click.echo(
            f"  Primary: {primary.get('metric')} {primary.get('direction', '>')} {primary.get('target')}"
        )
    click.echo()




# Register imported agent commands
command("advisor", requires_project=True, description="Ask the advisor agent a question")(cmd_advisor)
command("evaluate", requires_project=True, description="Run evaluator on an experiment")(cmd_evaluate)
command("plan", requires_project=True, description="Run planning agent to design a method")(cmd_plan)
command("report", requires_project=True, description="Generate reports")(cmd_report)
command("present", requires_project=True, description="Generate presentation for an experiment")(cmd_present)
command("finalize", requires_project=True, description="Finalize project \u2014 methods, report, presentation")(cmd_finalize)
command("build-tool", requires_project=True, description="Build a custom tool for the project")(cmd_build_tool)


@command("inspect", requires_project=True, description="Inspect dataset")
def cmd_inspect(session: ReplSession, args: str) -> None:
    from urika.cli import inspect as cli_inspect

    ctx = click.Context(cli_inspect)
    ctx.invoke(
        cli_inspect, project=session.project_name, data_file=args.strip() or None
    )


@command("logs", requires_project=True, description="Show experiment logs")
def cmd_logs(session: ReplSession, args: str) -> None:
    from urika.cli import logs as cli_logs

    ctx = click.Context(cli_logs)
    ctx.invoke(
        cli_logs, project=session.project_name, experiment_id=args.strip() or None
    )


@command(
    "knowledge", requires_project=True, description="Search, list, or ingest knowledge"
)
def cmd_knowledge(session: ReplSession, args: str) -> None:
    from urika.knowledge import KnowledgeStore

    arg = args.strip()
    store = KnowledgeStore(session.project_path)

    # /knowledge ingest <path>
    if arg.startswith("ingest "):
        source = arg[7:].strip()
        if not source:
            click.echo("  Usage: /knowledge ingest <path>")
            return
        try:
            entry = store.ingest(source)
            click.echo(f'  Ingested: {entry.id} "{entry.title}" ({entry.source_type})')
        except (FileNotFoundError, ValueError) as exc:
            click.echo(f"  Error: {exc}")
        return

    # /knowledge <query> — search
    if arg:
        results = store.search(arg)
        if not results:
            click.echo("  No results.")
            return
        for entry in results:
            snippet = entry.content[:80].replace("\n", " ")
            click.echo(f"    {entry.id}  {entry.title}  {_C.DIM}{snippet}{_C.RESET}")
    else:
        # /knowledge — list all
        entries = store.list_all()
        if not entries:
            click.echo("  No knowledge entries.")
            return
        for entry in entries:
            click.echo(f"    {entry.id}  {entry.title}  [{entry.source_type}]")


@command(
    "update",
    requires_project=True,
    description="Update project description, question, or mode",
)
def cmd_update(session: ReplSession, args: str) -> None:
    parts = args.strip().split(None, 1) if args.strip() else []

    if parts and parts[0] == "history":
        from urika.core.revisions import load_revisions

        revs = load_revisions(session.project_path)
        if not revs:
            click.echo("  No revisions recorded.")
            return
        click.echo("\n  Revision history:\n")
        for r in revs:
            ts = r["timestamp"][:19].replace("T", " ")
            click.echo(f"  #{r['revision']}  {ts}  [{r['field']}]")
            old = r["old_value"][:60]
            new = r["new_value"][:60]
            click.echo(f"    Old: {old}")
            click.echo(f"    New: {new}")
            if r.get("reason"):
                click.echo(f"    Why: {r['reason']}")
            click.echo()
        return

    import os

    os.environ["URIKA_REPL"] = "1"
    try:
        from urika.cli import update_project

        ctx = click.Context(update_project)
        ctx.invoke(
            update_project,
            project=session.project_name,
        )
    finally:
        os.environ.pop("URIKA_REPL", None)


@command(
    "dashboard",
    description="Open the project dashboard in your browser",
)
def cmd_dashboard(session: ReplSession, args: str) -> None:
    """Open the dashboard for the current project (or projects list).

    Starts the FastAPI dashboard on a random free port in a daemon
    thread, opens the browser at the right URL, and stashes the
    server reference on the session so it can be shut down on app
    exit.

    Usage::

        /dashboard         open dashboard (current project, or
                           projects list if none loaded)
        /dashboard stop    shut down all running dashboards
    """
    from urika.tui.dashboard_launcher import start_dashboard_server

    parts = args.strip().split()

    # /dashboard stop — shut down running servers
    if parts and parts[0] in ("stop", "--stop"):
        servers = getattr(session, "_dashboard_servers", None) or []
        if not servers:
            click.echo("  No dashboard running.")
            return
        for srv in servers:
            try:
                srv.should_exit = True
            except Exception:
                pass
        session._dashboard_servers = []
        click.echo(f"  Stopped {len(servers)} dashboard(s).")
        return

    open_path = "/projects"
    if session.has_project and session.project_name:
        open_path = f"/projects/{session.project_name}"

    try:
        server, _thread, port = start_dashboard_server(open_path=open_path)
    except Exception as exc:
        click.echo(f"  Cannot start dashboard: {exc}")
        return

    # Stash on session so app shutdown can stop it
    if hasattr(session, "_dashboard_servers") and isinstance(
        session._dashboard_servers, list
    ):
        session._dashboard_servers.append(server)
    else:
        session._dashboard_servers = [server]

    click.echo(f"  Dashboard at http://127.0.0.1:{port}{open_path}")
    click.echo("  /dashboard stop to shut down")


# ── Sibling-module imports (Phase 8 split) ─────────────────────────
# Importing these registers the @command decorators they declare so
# the slash commands defined there appear in GLOBAL_COMMANDS /
# PROJECT_COMMANDS exactly as if they had been declared here.
from urika.repl.commands_run import cmd_run  # noqa: E402, F401
from urika.repl.commands_session import (  # noqa: E402, F401
    cmd_resume,
    cmd_resume_session,
    cmd_new_session,
)
