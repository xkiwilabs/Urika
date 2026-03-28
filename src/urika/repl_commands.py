"""Slash command handlers for the REPL."""

from __future__ import annotations
import asyncio
from pathlib import Path
import click
from urika.cli_display import _C
from urika.repl_session import ReplSession


# Registry of commands
GLOBAL_COMMANDS = {}
PROJECT_COMMANDS = {}

# Module-level callback for passing queued user input into the orchestrator.
# Set before invoking the CLI run command from the REPL, cleared after.
_user_input_callback = None


def command(name: str, requires_project: bool = False, description: str = ""):
    """Decorator to register a REPL command."""

    def decorator(func):
        entry = {"func": func, "description": description}
        if requires_project:
            PROJECT_COMMANDS[name] = entry
        else:
            GLOBAL_COMMANDS[name] = entry
        return func

    return decorator


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

    try:
        config = load_project_config(path)
    except FileNotFoundError:
        click.echo(f"  Project directory missing: {path}")
        return

    session.load_project(path, name)

    experiments = list_experiments(path)
    completed = sum(
        1
        for e in experiments
        if load_progress(path, e.experiment_id).get("status") == "completed"
    )

    click.echo()
    print_success(f"Project: {name} \u00b7 {config.mode}")
    click.echo(f"    {len(experiments)} experiments \u00b7 {completed} completed")
    click.echo()


@command("new", description="Create a new project")
def cmd_new(session: ReplSession, args: str) -> None:
    import os as _os

    from urika.cli import new as cli_new
    from urika.core.registry import ProjectRegistry

    name = args.strip() if args.strip() else None

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
    except SystemExit:
        pass
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


@command("quit", description="Exit Urika")
def cmd_quit(session: ReplSession, args: str) -> None:
    session.save_usage()
    raise SystemExit(0)




@command("config", description="Configure privacy mode and models")
def cmd_config(session: ReplSession, args: str) -> None:
    from urika.cli import config_command

    arg = args.strip()
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
            cost_str += " (estimated — plan user)"
        click.echo(
            f"  This session: {elapsed} · {_fmt_tokens(tokens)} tokens · "
            f"{cost_str} · {session.agent_calls} agent calls"
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
                    f"  {name}: {totals['sessions']} sessions · "
                    f"{_fmt_tokens(tokens)} tokens · "
                    f"~${totals['total_cost_usd']:.2f}"
                )
                grand_tokens += tokens
                grand_cost += totals["total_cost_usd"]
                grand_calls += totals["total_agent_calls"]
                grand_sessions += totals["sessions"]
        if grand_sessions > 0:
            click.echo(
                f"\n  {_C.BOLD}Total: {grand_sessions} sessions · "
                f"{_fmt_tokens(grand_tokens)} tokens · "
                f"~${grand_cost:.2f} · {grand_calls} agent calls{_C.RESET}"
            )
    click.echo()


def _fmt_tokens(n: int) -> str:
    """Format token count."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


# Project-specific commands


@command("status", requires_project=True, description="Show project status")
def cmd_status(session: ReplSession, args: str) -> None:
    from urika.cli import status as cli_status

    # Call the existing status function
    ctx = click.Context(cli_status)
    ctx.invoke(cli_status, name=session.project_name)


@command("run", requires_project=True, description="Run next experiment")
def cmd_run(session: ReplSession, args: str) -> None:
    import click as _click
    from urika.cli_display import print_warning
    from urika.core.experiment import list_experiments

    # Check if any experiment is already running (lockfile exists)
    experiments = list_experiments(session.project_path)
    for exp in experiments:
        lock = session.project_path / "experiments" / exp.experiment_id / ".lock"
        if lock.exists():
            print_warning(f"Experiment '{exp.experiment_id}' is currently running.")
            choice = _prompt_numbered(
                "  What would you like to do?",
                [
                    "Wait for it to complete (recommended)",
                    "Stop it and start a new run",
                    "Cancel",
                ],
                default=1,
            )
            if choice.startswith("Wait"):
                click.echo("  Waiting is recommended. Check back after it completes.")
                return
            if choice.startswith("Cancel"):
                return
            # Stop it
            try:
                from urika.core.session import fail_session

                fail_session(
                    session.project_path,
                    exp.experiment_id,
                    error="Stopped by user from REPL",
                )
                click.echo(f"  Stopped {exp.experiment_id}")
            except Exception:
                lock.unlink(missing_ok=True)
            break

    # Show defaults, offer custom
    defaults = _load_run_defaults(session)
    click.echo("\n  Run settings:")
    click.echo(f"    Max turns: {defaults['max_turns']}")
    click.echo(f"    Auto mode: {defaults['auto_mode']}")
    instructions = (
        session.get_conversation_context() if session.conversation else "(none)"
    )
    click.echo(
        f"    Instructions: {instructions[:80]}{'...' if len(instructions) > 80 else ''}"
    )

    choice = _prompt_numbered(
        "\n  Proceed?",
        ["Run with defaults", "Custom settings", "Skip"],
        default=1,
    )

    if choice == "Skip":
        return

    max_turns = defaults["max_turns"]
    auto_mode = defaults["auto_mode"]
    max_experiments = None
    run_instructions = ""
    review_criteria = False

    if choice == "Custom settings":
        max_turns = int(
            _click.prompt("  Max turns", default=str(defaults["max_turns"]))
        )
        auto_mode = _prompt_numbered(
            "\n  Auto mode:",
            [
                "Checkpoint — pause between experiments for review",
                "Capped — run up to max experiments with no pauses",
                "Unlimited — run until criteria met or advisor says done",
            ],
            default={"checkpoint": 1, "capped": 2, "unlimited": 3}.get(
                defaults["auto_mode"], 1
            ),
        )
        # Map back to short name
        auto_mode = {
            "Checkpoint": "checkpoint",
            "Capped": "capped",
            "Unlimited": "unlimited",
        }.get(auto_mode.split("—")[0].strip(), "checkpoint")
        if auto_mode == "capped":
            max_experiments = int(_click.prompt("  Max experiments", default="10"))
        elif auto_mode == "unlimited":
            max_experiments = 50  # safety cap
        run_instructions = _click.prompt(
            "  Instructions (optional, enter to skip)", default=""
        )
        rc_choice = _prompt_numbered(
            "\n  Re-evaluate criteria if met?",
            [
                "No — complete when criteria met (default)",
                "Yes — advisor reviews criteria, may raise the bar",
            ],
            default=1,
        )
        review_criteria = rc_choice.startswith("Yes")

    # Use conversation context as instructions if none provided
    if not run_instructions and session.conversation:
        run_instructions = session.get_conversation_context()

    # Run directly without going through CLI (avoids duplicate header)
    import os

    global _user_input_callback  # noqa: PLW0603

    def _get_user_input() -> str:
        return session.pop_queued_input()

    os.environ["URIKA_REPL"] = "1"
    _user_input_callback = _get_user_input
    try:
        from urika.cli import run as cli_run

        ctx = click.Context(cli_run)
        ctx.invoke(
            cli_run,
            project=session.project_name,
            experiment_id=None,
            max_turns=max_turns,
            resume=False,
            quiet=False,
            auto=(auto_mode != "checkpoint"),
            instructions=run_instructions,
            max_experiments=max_experiments,
            review_criteria=review_criteria,
        )
        session.experiments_run += 1
    finally:
        _user_input_callback = None
        os.environ.pop("URIKA_REPL", None)


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


@command(
    "resume", requires_project=True, description="Resume a paused/failed experiment"
)
def cmd_resume(session: ReplSession, args: str) -> None:
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    experiments = list_experiments(session.project_path)
    resumable = []
    for exp in experiments:
        progress = load_progress(session.project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        if status in ("paused", "failed"):
            resumable.append((exp, status))

    if not resumable:
        click.echo("  No paused or failed experiments to resume.")
        return

    # If multiple, let user pick; if one, use it directly
    if len(resumable) == 1:
        exp, status = resumable[0]
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

    os.environ["URIKA_REPL"] = "1"
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
            auto=(defaults["auto_mode"] != "checkpoint"),
            instructions="",
            max_experiments=None,
        )
    finally:
        os.environ.pop("URIKA_REPL", None)


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


def _pick_experiment(
    session: ReplSession, args: str, allow_all: bool = False
) -> str | None:
    """Prompt user to pick an experiment. Returns exp_id, 'all', 'project', or None."""
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    exp_id = args.strip()
    if exp_id:
        return exp_id

    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No experiments.")
        return None

    # Build options — most recent first
    reversed_exps = list(reversed(experiments))
    options = []
    for exp in reversed_exps:
        progress = load_progress(session.project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        runs = len(progress.get("runs", []))
        options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
    if allow_all:
        options.append("All experiments (generate for each)")
        options.append("Project level (one overarching report)")

    choice = _prompt_numbered("\n  Select:", options, default=1)

    if choice.startswith("All"):
        return "all"
    if choice.startswith("Project"):
        return "project"

    # Extract exp_id from the choice string
    return choice.split(" [")[0]


@command(
    "present",
    requires_project=True,
    description="Generate presentation for an experiment",
)
def cmd_present(session: ReplSession, args: str) -> None:
    exp_choice = _pick_experiment(session, args, allow_all=True)
    if exp_choice is None:
        return

    if exp_choice == "all":
        # Generate presentation for each experiment
        from urika.core.experiment import list_experiments

        experiments = list_experiments(session.project_path)
        for exp in experiments:
            click.echo(
                f"  {_C.BLUE}Generating presentation for {exp.experiment_id}...{_C.RESET}"
            )
            text = _run_single_agent(
                session,
                "presentation_agent",
                exp.experiment_id,
                f"Create a presentation for experiment {exp.experiment_id}.",
            )
            if text:
                _save_presentation(session, text, exp.experiment_id)
        click.echo("  \u2713 All presentations generated")
    elif exp_choice == "project":
        # One project-level presentation covering everything
        click.echo(f"  {_C.BLUE}Generating project-level presentation...{_C.RESET}")
        text = _run_single_agent(
            session,
            "presentation_agent",
            "",
            "Create a project-level presentation covering ALL experiments, "
            "the research progression, key findings across the entire project, "
            "and next steps. This is an overview presentation, not per-experiment.",
        )
        if text:
            _save_presentation(session, text, None)
    else:
        # Single experiment presentation
        text = _run_single_agent(
            session,
            "presentation_agent",
            exp_choice,
            f"Create a presentation for experiment {exp_choice}.",
        )
        if text:
            _save_presentation(session, text, exp_choice)


@command("report", requires_project=True, description="Generate reports")
def cmd_report(session: ReplSession, args: str) -> None:
    exp_choice = _pick_experiment(session, args, allow_all=True)
    if exp_choice is None:
        return

    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )
    from urika.core.readme_generator import write_readme

    if exp_choice == "all":
        # Generate reports for each experiment
        click.echo(f"  {_C.BLUE}Generating reports for all experiments...{_C.RESET}")
        from urika.core.experiment import list_experiments

        for exp in list_experiments(session.project_path):
            click.echo(f"  {_C.BLUE}Processing {exp.experiment_id}...{_C.RESET}")
            try:
                update_experiment_notes(session.project_path, exp.experiment_id)
                generate_experiment_summary(session.project_path, exp.experiment_id)
            except Exception:
                pass
            text = _run_single_agent(
                session,
                "report_agent",
                exp.experiment_id,
                f"Write a detailed narrative report for experiment {exp.experiment_id}.",
            )
            if text:
                from urika.core.report_writer import write_versioned

                narrative_path = (
                    session.project_path
                    / "experiments"
                    / exp.experiment_id
                    / "labbook"
                    / "narrative.md"
                )
                narrative_path.parent.mkdir(parents=True, exist_ok=True)
                write_versioned(narrative_path, text + "\n")
        click.echo("  \u2713 All experiment reports updated")
    elif exp_choice == "project":
        # Project-level reports
        click.echo(f"  {_C.BLUE}Generating project-level reports...{_C.RESET}")
        try:
            generate_results_summary(session.project_path)
            generate_key_findings(session.project_path)
            write_readme(session.project_path)
        except Exception:
            pass

        text = _run_single_agent(
            session,
            "report_agent",
            "",
            "Write a project-level narrative report covering all experiments and the research progression.",
        )
        if text:
            from urika.core.report_writer import write_versioned

            narrative_path = session.project_path / "projectbook" / "narrative.md"
            narrative_path.parent.mkdir(parents=True, exist_ok=True)
            write_versioned(narrative_path, text + "\n")
            link = _file_link(narrative_path, "projectbook/narrative.md")
            click.echo(f"  \u2713 Project narrative: {link}")
            readme_link = _file_link(session.project_path / "README.md", "README.md")
            click.echo(f"  \u2713 README: {readme_link}")
    else:
        click.echo(f"  {_C.BLUE}Generating report for {exp_choice}...{_C.RESET}")
        try:
            update_experiment_notes(session.project_path, exp_choice)
            generate_experiment_summary(session.project_path, exp_choice)
            summary_path = (
                session.project_path
                / "experiments"
                / exp_choice
                / "labbook"
                / "summary.md"
            )
            link = _file_link(
                summary_path, f"experiments/{exp_choice}/labbook/summary.md"
            )
            click.echo(f"  \u2713 Report: {link}")
        except Exception as exc:
            click.echo(f"  \u2717 Error: {exc}")

        # Generate experiment narrative via report agent
        text = _run_single_agent(
            session,
            "report_agent",
            exp_choice,
            f"Write a detailed narrative report for experiment {exp_choice}.",
        )
        if text:
            from urika.core.report_writer import write_versioned

            narrative_path = (
                session.project_path
                / "experiments"
                / exp_choice
                / "labbook"
                / "narrative.md"
            )
            narrative_path.parent.mkdir(parents=True, exist_ok=True)
            write_versioned(narrative_path, text + "\n")
            link = _file_link(
                narrative_path,
                f"experiments/{exp_choice}/labbook/narrative.md",
            )
            click.echo(f"  \u2713 Narrative: {link}")


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


@command("knowledge", requires_project=True, description="Search, list, or ingest knowledge")
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
    "advisor", requires_project=True, description="Ask the advisor agent a question"
)
def cmd_advisor(session: ReplSession, args: str) -> None:
    text = args.strip()
    if not text:
        click.echo("  Usage: /advisor <question or instructions>")
        return
    # Delegate to the free-text handler in repl.py
    from urika.repl import _handle_free_text

    _handle_free_text(session, text)


@command(
    "evaluate", requires_project=True, description="Run evaluator on an experiment"
)
def cmd_evaluate(session: ReplSession, args: str) -> None:
    exp_id = args.strip()
    if not exp_id:
        from urika.core.experiment import list_experiments

        experiments = list_experiments(session.project_path)
        if not experiments:
            click.echo("  No experiments.")
            return
        exp_id = experiments[-1].experiment_id

    click.echo(f"  Running evaluator on {exp_id}...")
    _run_single_agent(session, "evaluator", exp_id, f"Evaluate experiment {exp_id}.")


@command(
    "plan", requires_project=True, description="Run planning agent to design a method"
)
def cmd_plan(session: ReplSession, args: str) -> None:
    exp_id = args.strip()
    if not exp_id:
        from urika.core.experiment import list_experiments

        experiments = list_experiments(session.project_path)
        if not experiments:
            click.echo("  No experiments.")
            return
        exp_id = experiments[-1].experiment_id

    context = "Design the next method based on current results."
    if session.conversation:
        context = session.get_conversation_context() + "\n\n" + context

    click.echo(f"  Running planning agent for {exp_id}...")
    _run_single_agent(session, "planning_agent", exp_id, context)


@command(
    "finalize",
    requires_project=True,
    description="Finalize project — methods, report, presentation",
)
def cmd_finalize(session: ReplSession, args: str) -> None:
    import os

    instructions = args.strip()
    os.environ["URIKA_REPL"] = "1"
    try:
        from urika.cli import finalize as cli_finalize

        ctx = click.Context(cli_finalize)
        ctx.invoke(
            cli_finalize,
            project=session.project_name,
            instructions=instructions,
        )
    finally:
        os.environ.pop("URIKA_REPL", None)


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
            click.echo(
                f"  #{r['revision']}  {ts}  "
                f"[{r['field']}]"
            )
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
    "build-tool",
    requires_project=True,
    description="Build a custom tool for the project",
)
def cmd_build_tool(session: ReplSession, args: str) -> None:
    instructions = args.strip()
    if not instructions:
        click.echo(
            "  Usage: /build-tool <instructions>\n"
            "  Examples:\n"
            "    /build-tool create an EEG epoch extractor using MNE\n"
            "    /build-tool build a tool that computes ICC using pingouin\n"
            "    /build-tool install librosa and create an audio feature extractor"
        )
        return

    _run_single_agent(session, "tool_builder", "", instructions)


def _run_single_agent(
    session: ReplSession, agent_name: str, experiment_id: str, prompt: str
) -> str:
    """Run a single agent and display its output. Returns the text output."""
    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
        from urika.cli import _make_on_message
        from urika.cli_display import Spinner, print_agent, print_error

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()

        role = registry.get(agent_name)
        if role is None:
            print_error(f"Agent '{agent_name}' not found.")
            return ""

        print_agent(agent_name)

        _on_msg = _make_on_message()

        config = role.build_config(
            project_dir=session.project_path, experiment_id=experiment_id
        )

        session_info = {
            "project": session.project_name or "",
            "model": session.model or "",
            "tokens": session.total_tokens_in + session.total_tokens_out,
            "cost": session.total_cost_usd,
        }
        with Spinner("Working", session_info=session_info) as sp:

            def _on_msg_with_footer(msg: object) -> None:
                _on_msg(msg)
                model = getattr(msg, "model", None)
                if model:
                    sp.update_session(model=model)

            result = asyncio.run(
                runner.run(config, prompt, on_message=_on_msg_with_footer)
            )

        # Track usage
        session.record_agent_call(
            tokens_in=getattr(result, "tokens_in", 0) or 0,
            tokens_out=getattr(result, "tokens_out", 0) or 0,
            cost_usd=result.cost_usd or 0.0,
            model=getattr(result, "model", "") or "",
        )

        if result.success and result.text_output:
            click.echo(f"\n{result.text_output.strip()}\n")
            return result.text_output.strip()
        else:
            print_error(f"Error: {result.error}")
            return ""

    except ImportError:
        from urika.cli_display import print_error

        print_error("Claude Agent SDK not installed. Run: pip install urika[agents]")
        return ""
    except Exception as exc:
        from urika.cli_display import print_error

        print_error(f"Error: {exc}")
        return ""


def get_global_stats() -> dict:
    """Get global Urika stats for the footer."""
    from urika.core.registry import ProjectRegistry

    stats = {"projects": 0, "experiments": 0, "methods": 0, "sdk": "unknown"}

    registry = ProjectRegistry()
    projects = registry.list_all()
    stats["projects"] = len(projects)

    for name, path in projects.items():
        try:
            from urika.core.experiment import list_experiments

            exps = list_experiments(path)
            stats["experiments"] += len(exps)
        except Exception:
            pass
        try:
            import json

            methods_path = path / "methods.json"
            if methods_path.exists():
                mdata = json.loads(methods_path.read_text())
                stats["methods"] += len(mdata.get("methods", []))
        except Exception:
            pass

    try:
        import claude_agent_sdk

        stats["sdk"] = f"claude-agent-sdk {claude_agent_sdk.__version__}"
    except (ImportError, AttributeError):
        stats["sdk"] = "not installed"

    return stats


def _load_run_defaults(session: ReplSession) -> dict:
    """Load run defaults from urika.toml preferences."""
    import tomllib

    defaults = {"max_turns": 5, "auto_mode": "checkpoint"}
    toml_path = session.project_path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            prefs = data.get("preferences", {})
            defaults["max_turns"] = prefs.get("max_turns_per_experiment", 5)
            defaults["auto_mode"] = prefs.get("auto_mode", "checkpoint")
        except Exception:
            pass
    return defaults


def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt with numbered options."""
    click.echo(prompt_text)
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i == default else ""
        click.echo(f"    {i}. {opt}{marker}")
    while True:
        try:
            raw = click.prompt("  Choice", default=str(default)).strip()
        except (EOFError, KeyboardInterrupt):
            return options[default - 1]
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass


def get_all_commands(session: ReplSession) -> dict:
    """Get all available commands for current state."""
    cmds = dict(GLOBAL_COMMANDS)
    if session.has_project:
        cmds.update(PROJECT_COMMANDS)
    return cmds


def get_command_names(session: ReplSession) -> list[str]:
    """Get all command names for tab completion."""
    return sorted(get_all_commands(session).keys())


def get_project_names() -> list[str]:
    """Get all project names for tab completion."""
    from urika.core.registry import ProjectRegistry

    registry = ProjectRegistry()
    return sorted(registry.list_all().keys())


def get_experiment_ids(session: ReplSession) -> list[str]:
    """Get experiment IDs for tab completion."""
    if not session.has_project:
        return []
    from urika.core.experiment import list_experiments

    return [e.experiment_id for e in list_experiments(session.project_path)]


def _save_presentation(session: ReplSession, text: str, exp_id: str | None) -> None:
    """Parse slide JSON and render presentation, with clickable output link."""
    import tomllib

    from urika.core.presentation import parse_slide_json, render_presentation

    slide_data = parse_slide_json(text)
    if not slide_data:
        click.echo("  \u2717 Could not parse slide data from agent output")
        return

    theme = "light"
    toml_path = session.project_path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tdata = tomllib.load(f)
            theme = tdata.get("preferences", {}).get("presentation_theme", "light")
        except Exception:
            pass

    if exp_id:
        exp_dir = session.project_path / "experiments" / exp_id
        output_dir = exp_dir / "presentation"
        render_presentation(slide_data, output_dir, theme=theme, experiment_dir=exp_dir)
        display = f"experiments/{exp_id}/presentation/index.html"
    else:
        output_dir = session.project_path / "projectbook" / "presentation"
        render_presentation(slide_data, output_dir, theme=theme)
        display = "projectbook/presentation/index.html"

    pres_path = output_dir / "index.html"
    link = _file_link(pres_path, display)
    click.echo(f"  \u2713 Saved: {link}")


def _file_link(path: Path, display: str = "") -> str:
    """Create a clickable terminal hyperlink using OSC 8 escape sequence."""
    import sys

    label = display or str(path)
    if not sys.stdout.isatty():
        return label
    uri = path.resolve().as_uri()
    return f"\033]8;;{uri}\033\\{label}\033]8;;\033\\"
