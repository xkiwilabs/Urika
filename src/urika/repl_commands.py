"""Slash command handlers for the REPL."""

from __future__ import annotations
import asyncio
from pathlib import Path
import click
from urika.repl_session import ReplSession


# Registry of commands
GLOBAL_COMMANDS = {}
PROJECT_COMMANDS = {}


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
    from urika.cli_display import _C

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
        # Could check for running experiments here
        pass

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
    # Calls the same project builder flow as CLI
    from urika.cli import new as cli_new
    from click.testing import CliRunner

    runner = CliRunner(mix_stderr=False)
    runner.invoke(cli_new, [], standalone_mode=False, catch_exceptions=False)
    # After creation, auto-load the project
    # (handled by checking registry for latest)


@command("quit", description="Exit Urika")
def cmd_quit(session: ReplSession, args: str) -> None:
    raise SystemExit(0)


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
    run_instructions = ""

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
            _max_exp = int(_click.prompt("  Max experiments", default="10"))
            # TODO: pass _max_exp to meta-orchestrator when wired
            _ = _max_exp
        run_instructions = _click.prompt(
            "  Instructions (optional, enter to skip)", default=""
        )

    # Use conversation context as instructions if none provided
    if not run_instructions and session.conversation:
        run_instructions = session.get_conversation_context()

    # Run directly without going through CLI (avoids duplicate header)
    import os

    os.environ["URIKA_REPL"] = "1"
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
        )
    finally:
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


@command(
    "present",
    requires_project=True,
    description="Generate presentation for an experiment",
)
def cmd_present(session: ReplSession, args: str) -> None:
    exp_id = args.strip()
    if not exp_id:
        # Use latest experiment
        from urika.core.experiment import list_experiments

        experiments = list_experiments(session.project_path)
        if not experiments:
            click.echo("  No experiments.")
            return
        exp_id = experiments[-1].experiment_id

    click.echo(f"  Generating presentation for {exp_id}...")
    try:
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.orchestrator.loop import _generate_presentation, _noop_callback

        runner = ClaudeSDKRunner()
        asyncio.run(
            _generate_presentation(session.project_path, exp_id, runner, _noop_callback)
        )
        pres_path = (
            session.project_path
            / "experiments"
            / exp_id
            / "presentation"
            / "index.html"
        )
        link = _file_link(pres_path, f"experiments/{exp_id}/presentation/index.html")
        click.echo(f"  \u2713 Saved: {link}")
    except Exception as exc:
        click.echo(f"  \u2717 Error: {exc}")


@command("report", requires_project=True, description="Generate reports")
def cmd_report(session: ReplSession, args: str) -> None:
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )
    from urika.core.experiment import list_experiments
    from urika.core.readme_generator import write_readme

    click.echo("  Generating reports...")
    for exp in list_experiments(session.project_path):
        try:
            update_experiment_notes(session.project_path, exp.experiment_id)
            generate_experiment_summary(session.project_path, exp.experiment_id)
        except Exception:
            pass
    try:
        generate_results_summary(session.project_path)
        generate_key_findings(session.project_path)
        write_readme(session.project_path)
    except Exception:
        pass
    click.echo("  \u2713 Reports updated")


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


@command("knowledge", requires_project=True, description="Search knowledge base")
def cmd_knowledge(session: ReplSession, args: str) -> None:
    from urika.knowledge import KnowledgeStore

    store = KnowledgeStore(session.project_path)
    if args.strip():
        results = store.search(args.strip())
        if not results:
            click.echo("  No results.")
            return
        for entry in results:
            click.echo(f"    {entry.id}  {entry.title}")
    else:
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


def _run_single_agent(
    session: ReplSession, agent_name: str, experiment_id: str, prompt: str
) -> None:
    """Run a single agent and display its output."""
    try:
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.agents.registry import AgentRegistry
        from urika.cli_display import Spinner, print_agent, print_error, print_tool_use

        runner = ClaudeSDKRunner()
        registry = AgentRegistry()
        registry.discover()

        role = registry.get(agent_name)
        if role is None:
            print_error(f"Agent '{agent_name}' not found.")
            return

        print_agent(agent_name)

        def _on_msg(msg: object) -> None:
            try:
                if hasattr(msg, "content"):
                    for block in msg.content:
                        tool_name = getattr(block, "name", None)
                        if tool_name:
                            inp = getattr(block, "input", {}) or {}
                            detail = ""
                            if isinstance(inp, dict):
                                detail = (
                                    inp.get("command", "")
                                    or inp.get("file_path", "")
                                    or inp.get("pattern", "")
                                )
                            print_tool_use(tool_name, detail)
            except Exception:
                pass

        config = role.build_config(
            project_dir=session.project_path, experiment_id=experiment_id
        )

        with Spinner("Working"):
            result = asyncio.run(runner.run(config, prompt, on_message=_on_msg))

        if result.success and result.text_output:
            click.echo(f"\n{result.text_output.strip()}\n")
        else:
            print_error(f"Error: {result.error}")

    except ImportError:
        from urika.cli_display import print_error

        print_error("Claude Agent SDK not installed.")
    except Exception as exc:
        from urika.cli_display import print_error

        print_error(f"Error: {exc}")


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
        raw = click.prompt("  Choice", default=str(default)).strip()
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


def _file_link(path: Path, display: str = "") -> str:
    """Create a clickable terminal hyperlink using OSC 8 escape sequence."""
    import sys

    label = display or str(path)
    if not sys.stdout.isatty():
        return label
    uri = path.resolve().as_uri()
    return f"\033]8;;{uri}\033\\{label}\033]8;;\033\\"
