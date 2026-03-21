"""Urika CLI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from urika.core.experiment import create_experiment, list_experiments
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.workspace import load_project_config
from urika.evaluation.leaderboard import load_leaderboard
from urika.tools import ToolRegistry


def _projects_dir() -> Path:
    """Default directory for new projects."""
    env = os.environ.get("URIKA_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path.home() / "urika-projects"


def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name. Raises ClickException on error."""
    registry = ProjectRegistry()
    project_path = registry.get(name)
    if project_path is None:
        raise click.ClickException(f"Project '{name}' not found in registry.")
    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise click.ClickException(f"Project directory missing at {project_path}")
    return project_path, config


@click.group()
@click.version_option(package_name="urika")
def cli() -> None:
    """Urika: Agentic scientific analysis platform."""


def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt user with numbered options. Returns the selected option text."""
    click.echo(prompt_text)
    for i, opt in enumerate(options, 1):
        marker = " (default, press enter)" if i == default else ""
        click.echo(f"  {i}. {opt}{marker}")
    while True:
        raw = click.prompt("Choice", default=str(default)).strip()
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        click.echo(f"Please enter a number between 1 and {len(options)}.")


def _prompt_path(prompt_text: str, must_exist: bool = True) -> str | None:
    """Prompt for a path, re-asking if it doesn't exist. Empty = skip."""
    while True:
        raw = click.prompt(prompt_text, default="").strip()
        if not raw:
            return None
        resolved = Path(raw).resolve()
        if not must_exist or resolved.exists():
            return str(resolved)
        click.echo(f"  Path not found: {raw}")
        click.echo("  Please check the path and try again.")


@cli.command()
@click.argument("name", required=False, default=None)
@click.option("-q", "--question", default=None, help="Research question.")
@click.option(
    "-m",
    "--mode",
    default=None,
    type=click.Choice(["exploratory", "confirmatory", "pipeline"]),
    help="Investigation mode.",
)
@click.option(
    "--data", "data_path", default=None, help="Path to data file or directory."
)
@click.option("--description", default=None, help="Project description.")
def new(
    name: str | None,
    question: str | None,
    mode: str | None,
    data_path: str | None,
    description: str | None,
) -> None:
    """Create a new project."""
    from urika.cli_display import (
        Spinner,
        print_agent,
        print_error,
        print_header,
        print_success,
    )
    from urika.core.project_builder import ProjectBuilder

    # Show welcome header immediately
    print_header()

    # Prompt for missing required fields
    if name is None:
        name = click.prompt("Project name").strip()

    # Validate data path — keep asking until valid or skipped
    if data_path is not None:
        data_path = data_path.strip()
        resolved = Path(data_path).resolve()
        if not resolved.exists():
            click.echo(f"  Path not found: {data_path}")
            data_path = _prompt_path("Path to data (file or directory)")
        else:
            data_path = str(resolved)
    else:
        data_path = _prompt_path("Path to data (file or directory)")

    if description is None:
        description = click.prompt(
            "Describe the project — what are you trying to analyse or predict",
            default="",
        ).strip()
    if question is None:
        question = click.prompt("Research question").strip()
    if mode is None:
        mode = _prompt_numbered(
            "Investigation mode:",
            ["exploratory", "confirmatory", "pipeline"],
            default=1,
        )

    source = Path(data_path) if data_path else None
    builder = ProjectBuilder(
        name=name,
        source_path=source,
        projects_dir=_projects_dir(),
        description=description or "",
        question=question,
        mode=mode,
    )

    # Check if project already exists before doing work
    project_dir = _projects_dir() / name
    while (project_dir / "urika.toml").exists():
        choice = _prompt_numbered(
            f"Project '{name}' already exists:",
            ["Overwrite", "New name", "Abort"],
            default=1,
        )
        if choice == "Abort":
            raise click.ClickException("Aborted.")
        if choice == "Overwrite":
            import shutil

            shutil.rmtree(project_dir)
            break
        # New name
        name = click.prompt("New project name").strip()
        builder.name = name
        project_dir = _projects_dir() / name

    # Show project details header
    print_header(
        project_name=name,
        mode=mode,
        data_source=data_path or "",
    )

    # Scan and profile if a data path was provided
    scan_result = None
    data_summary = None
    has_knowledge = False
    if data_path:
        with Spinner("Scanning data source"):
            scan_result = builder.scan()
        click.echo(scan_result.summary())

        has_knowledge = bool(scan_result.docs or scan_result.papers or scan_result.code)

        with Spinner("Profiling data files"):
            try:
                data_summary = builder.profile_data()
                print_success(
                    f"Data profile: {data_summary.n_rows} rows,"
                    f" {data_summary.n_columns} columns"
                )
            except (ValueError, Exception):
                pass

    # --- Interactive agent loop ---
    print_agent("project_builder")
    try:
        _run_builder_agent_loop(
            builder, scan_result, data_summary, description or "", question
        )
    except Exception as exc:
        print_error(f"Agent loop unavailable ({exc}). Continuing with manual setup.")

    with Spinner("Writing project files"):
        project_dir = builder.write_project()

    # Ingest knowledge if available
    if data_path and scan_result and has_knowledge:
        ingest = click.confirm(
            "\nIngest documentation and papers into the knowledge base?",
            default=True,
        )
        if ingest:
            with Spinner("Ingesting knowledge"):
                _ingest_knowledge(project_dir, scan_result)

    registry = ProjectRegistry()
    registry.register(name, project_dir)

    print_success(f"Created project '{name}' at {project_dir}")

    # Offer to run the first planned experiment
    import json

    suggestions_path = project_dir / "suggestions" / "initial.json"
    if suggestions_path.exists():
        try:
            sdata = json.loads(suggestions_path.read_text())
            first = (sdata.get("suggestions") or [{}])[0]
            first_name = first.get("name", "")
            first_desc = first.get("method", first.get("description", ""))
        except (json.JSONDecodeError, IndexError, KeyError):
            first_name = ""
            first_desc = ""

        if first_name:
            short_desc = (
                first_desc[:120] + "..." if len(first_desc) > 120 else first_desc
            )
            click.echo(f"\n  The plan proposes starting with: {first_name}")
            if short_desc:
                click.echo(f"    {short_desc}")

            choice = _prompt_numbered(
                "\n  Run the first experiment?",
                [
                    "Yes — create and run it",
                    "Different — I'll describe what to run instead",
                    "Skip — I'll run it later",
                ],
                default=1,
            )

            if choice.startswith("Skip"):
                pass
            else:
                if choice.startswith("Different"):
                    custom = click.prompt("  Describe the experiment").strip()
                    exp_name = click.prompt(
                        "  Experiment name", default="custom-experiment"
                    ).strip()
                    exp = create_experiment(
                        project_dir,
                        name=exp_name,
                        hypothesis=custom,
                    )
                else:
                    exp = create_experiment(
                        project_dir,
                        name=first_name.replace(" ", "-").lower(),
                        hypothesis=first_desc[:500] if first_desc else "",
                    )

                click.echo(f"\n  Created experiment: {exp.experiment_id}")
                click.echo("  Starting orchestrator...\n")
                # Launch the run command programmatically
                ctx = click.get_current_context()
                ctx.invoke(
                    run,
                    project=name,
                    experiment_id=exp.experiment_id,
                    max_turns=50,
                    resume=False,
                )


def _run_builder_agent_loop(
    builder: object,
    scan_result: object,
    data_summary: object,
    description: str,
    question: str,
) -> None:
    """Run the interactive agent loop: questions → suggestions → plan."""
    import asyncio

    from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
    from urika.agents.registry import AgentRegistry
    from urika.cli_display import (
        Spinner,
        _AGENT_ACTIVITY,
        print_agent,
        print_error,
        print_step,
        print_tool_use,
        thinking_phrase,
    )
    from urika.core.builder_prompts import (
        build_planning_prompt,
        build_scoping_prompt,
        build_suggestion_prompt,
    )
    from urika.orchestrator.parsing import (
        _extract_json_blocks,
        parse_suggestions,
    )

    def _on_builder_msg(msg: object) -> None:
        """Show tool use from builder agents."""
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

    runner = ClaudeSDKRunner()
    registry = AgentRegistry()
    registry.discover()

    # --- Phase 1: Clarifying questions ---
    builder_role = registry.get("project_builder")
    if builder_role is None:
        print_error("Project builder agent not found. Skipping interactive scoping.")
        return

    if scan_result is None:
        print_error("No data scanned. Skipping interactive scoping.")
        return

    answers: dict[str, str] = {}
    context = ""
    max_questions = 5

    print_step("The project builder will ask a few questions to scope the project.")

    for i in range(max_questions):
        prompt = build_scoping_prompt(
            scan_result, data_summary, description, context, question=question
        )
        config = builder_role.build_config(project_dir=builder.source_path)

        with Spinner(thinking_phrase()):
            result = asyncio.run(runner.run(config, prompt, on_message=_on_builder_msg))

        if not result.success:
            print_error(f"Agent error: {result.error}")
            break

        # Try to parse structured question from JSON block
        blocks = _extract_json_blocks(result.text_output)
        question_text = None
        for block in blocks:
            if "question" in block:
                question_text = block["question"]
                if block.get("options"):
                    click.echo(f"\n{question_text}")
                    for j, opt in enumerate(block["options"], 1):
                        click.echo(f"  {j}. {opt}")
                break

        if question_text is None:
            question_text = result.text_output.strip()
            if not question_text:
                break
            click.echo(f"\n{question_text}")

        answer = click.prompt("\nYour answer (or 'done' to move on)").strip()
        if answer.lower() == "done":
            break

        answers[question_text] = answer
        context += f"Q: {question_text}\nA: {answer}\n\n"

    # --- Phase 2: Advisor agent ---
    print_agent("advisor_agent")
    suggest_role = registry.get("advisor_agent")
    if suggest_role is None:
        print_error("Advisor agent not found. Skipping.")
        return

    suggest_prompt = build_suggestion_prompt(description, data_summary, answers)
    suggest_config = suggest_role.build_config(
        project_dir=builder.source_path, experiment_id=""
    )

    with Spinner(_AGENT_ACTIVITY.get("advisor_agent", thinking_phrase())):
        suggest_result = asyncio.run(
            runner.run(suggest_config, suggest_prompt, on_message=_on_builder_msg)
        )

    if not suggest_result.success:
        print_error(f"Advisor agent error: {suggest_result.error}")
        return

    suggestions = parse_suggestions(suggest_result.text_output)
    click.echo(suggest_result.text_output.strip())

    # --- Phase 3: Planning agent ---
    print_agent("planning_agent")
    plan_role = registry.get("planning_agent")
    if plan_role is None:
        print_error("Planning agent not found. Skipping.")
        if suggestions:
            builder.set_initial_suggestions(suggestions)
        return

    plan_prompt = build_planning_prompt(suggestions or {}, description, data_summary)
    plan_config = plan_role.build_config(
        project_dir=builder.source_path, experiment_id=""
    )

    with Spinner(_AGENT_ACTIVITY.get("planning_agent", thinking_phrase())):
        plan_result = asyncio.run(
            runner.run(plan_config, plan_prompt, on_message=_on_builder_msg)
        )

    if not plan_result.success:
        print_error(f"Planning agent error: {plan_result.error}")
        if suggestions:
            builder.set_initial_suggestions(suggestions)
        return

    click.echo(plan_result.text_output.strip())

    # --- Phase 4: User refinement loop ---
    while True:
        click.echo("")
        choice = _prompt_numbered(
            "What would you like to do?",
            ["Looks good — create the project", "Refine — I have suggestions", "Abort"],
            default=1,
        )
        if choice == "Abort":
            raise click.ClickException("Aborted.")
        if choice.startswith("Looks good"):
            break
        refinement = click.prompt("Your suggestions").strip()
        if not refinement:
            continue

        print_agent("advisor_agent")
        refined_prompt = suggest_prompt + f"\n\n## User Refinement\n{refinement}"
        with Spinner(_AGENT_ACTIVITY.get("advisor_agent", thinking_phrase())):
            suggest_result = asyncio.run(
                runner.run(suggest_config, refined_prompt, on_message=_on_builder_msg)
            )
        if suggest_result.success:
            suggestions = parse_suggestions(suggest_result.text_output)
            print_agent("planning_agent")
            plan_prompt = build_planning_prompt(
                suggestions or {}, description, data_summary
            )
            with Spinner(_AGENT_ACTIVITY.get("planning_agent", thinking_phrase())):
                plan_result = asyncio.run(
                    runner.run(plan_config, plan_prompt, on_message=_on_builder_msg)
                )
            if plan_result.success:
                click.echo(plan_result.text_output.strip())

    # Store final suggestions
    if suggestions:
        builder.set_initial_suggestions(suggestions)


def _ingest_knowledge(
    project_dir: Path,
    scan_result: object,
) -> None:
    """Ingest docs and papers into the project's knowledge store."""
    from urika.knowledge import KnowledgeStore

    store = KnowledgeStore(project_dir)
    ingested = 0
    for f in scan_result.docs + scan_result.papers:
        try:
            store.ingest(str(f))
            ingested += 1
        except Exception:
            pass
    if ingested:
        click.echo(f"Ingested {ingested} files into knowledge base.")


@cli.command("list")
def list_cmd() -> None:
    """List all registered projects."""
    registry = ProjectRegistry()
    projects = registry.list_all()

    if not projects:
        click.echo("No projects registered.")
        return

    for name, path in projects.items():
        exists = "  " if path.exists() else "? "
        click.echo(f"{exists}{name}  {path}")


@cli.command()
@click.argument("name")
def status(name: str) -> None:
    """Show project status."""
    project_path, config = _resolve_project(name)

    experiments = list_experiments(project_path)

    click.echo(f"Project: {config.name}")
    click.echo(f"Question: {config.question}")
    click.echo(f"Mode: {config.mode}")
    click.echo(f"Path: {project_path}")
    click.echo(f"Experiments: {len(experiments)}")

    if experiments:
        click.echo("")
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            n_runs = len(progress.get("runs", []))
            exp_status = progress.get("status", "unknown")
            click.echo(
                f"  {exp.experiment_id}: {exp.name} [{exp_status}, {n_runs} runs]"
            )


@cli.group()
def experiment() -> None:
    """Manage experiments within a project."""


@experiment.command("create")
@click.argument("project")
@click.argument("name")
@click.option("--hypothesis", default="", help="Experiment hypothesis.")
def experiment_create(project: str, name: str, hypothesis: str) -> None:
    """Create a new experiment in a project."""
    project_path, _config = _resolve_project(project)
    exp = create_experiment(project_path, name=name, hypothesis=hypothesis)
    click.echo(f"{exp.experiment_id}")


@experiment.command("list")
@click.argument("project")
def experiment_list(project: str) -> None:
    """List experiments in a project."""
    project_path, _config = _resolve_project(project)
    experiments = list_experiments(project_path)

    if not experiments:
        click.echo("No experiments yet.")
        return

    for exp in experiments:
        progress = load_progress(project_path, exp.experiment_id)
        n_runs = len(progress.get("runs", []))
        exp_status = progress.get("status", "unknown")
        click.echo(f"  {exp.experiment_id}  {exp.name}  [{exp_status}, {n_runs} runs]")


@cli.command()
@click.argument("project")
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Show runs for a specific experiment.",
)
def results(project: str, experiment_id: str | None) -> None:
    """Show project results (leaderboard or experiment runs)."""
    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        progress = load_progress(project_path, experiment_id)
        runs = progress.get("runs", [])
        if not runs:
            click.echo("No results yet.")
            return
        for run in runs:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in run.get("metrics", {}).items()
            )
            click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
        return

    leaderboard = load_leaderboard(project_path)
    ranking = leaderboard.get("ranking", [])

    if not ranking:
        click.echo("No results yet.")
        return

    for entry in ranking:
        metrics_str = ", ".join(f"{k}={v}" for k, v in entry.get("metrics", {}).items())
        click.echo(f"  #{entry['rank']}  {entry['method']}  {metrics_str}")


@cli.command()
@click.argument("project")
def methods(project: str) -> None:
    """List agent-created methods in a project."""
    from urika.methods import MethodRegistry

    project_path, _config = _resolve_project(project)
    registry = MethodRegistry()
    registry.discover_project(project_path / "methods")

    names = registry.list_all()
    if not names:
        click.echo("No methods created yet.")
        return

    for name in names:
        method = registry.get(name)
        if method is not None:
            tools = ", ".join(method.tools_used())
            click.echo(f"  {method.name()}  [{tools}]  {method.description()}")


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific tools.")
def tools(category: str | None, project: str | None) -> None:
    """List available analysis tools."""
    registry = ToolRegistry()
    registry.discover()

    if project is not None:
        project_path, _config = _resolve_project(project)
        registry.discover_project(project_path / "tools")

    if category is not None:
        names = registry.list_by_category(category)
    else:
        names = registry.list_all()

    if not names:
        click.echo("No tools found.")
        return

    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"  {tool.name()}  [{tool.category()}]  {tool.description()}")


def _determine_next_experiment(
    project_path: Path,
    project_name: str,
    *,
    auto: bool = False,
    panel: object = None,
    instructions: str = "",
) -> str | None:
    """Determine and create the next experiment based on project state.

    Reads methods.json, criteria.json, completed experiments, and the initial
    plan to decide what should run next. If the initial plan is exhausted,
    calls the suggestion agent for next steps.
    """
    import json

    from urika.cli_display import print_step, print_success

    # Gather project state
    existing_experiments = list_experiments(project_path)
    completed = [
        e
        for e in existing_experiments
        if load_progress(project_path, e.experiment_id).get("status") == "completed"
    ]

    # Load methods registry
    methods_path = project_path / "methods.json"
    methods_summary = ""
    if methods_path.exists():
        try:
            mdata = json.loads(methods_path.read_text())
            mlist = mdata.get("methods", [])
            if mlist:
                methods_summary = f"{len(mlist)} methods tried. Best: "
                best = max(
                    (m for m in mlist if m.get("metrics")),
                    key=lambda m: max(m["metrics"].values()) if m["metrics"] else 0,
                    default=None,
                )
                if best:
                    methods_summary += f"{best['name']} ({best.get('metrics', {})})"
        except (json.JSONDecodeError, KeyError):
            pass

    # Load criteria
    criteria_summary = ""
    criteria_path = project_path / "criteria.json"
    if criteria_path.exists():
        try:
            cdata = json.loads(criteria_path.read_text())
            versions = cdata.get("versions", [])
            if versions:
                latest = versions[-1]
                ctype = latest.get("criteria", {}).get("type", "unknown")
                criteria_summary = f"Criteria: {ctype} (v{latest['version']})"
        except (json.JSONDecodeError, KeyError):
            pass

    # If user provided instructions, always call advisor agent to think
    # Otherwise fall back to initial plan
    next_suggestion = None
    call_advisor_agent = bool(instructions) or bool(completed)

    if not call_advisor_agent:
        # First experiment, no instructions — use initial plan
        suggestions_path = project_path / "suggestions" / "initial.json"
        if suggestions_path.exists():
            try:
                data = json.loads(suggestions_path.read_text())
                suggestions = data.get("suggestions", [])
                if suggestions:
                    next_suggestion = suggestions[0]
            except (json.JSONDecodeError, KeyError):
                pass

    # Call suggestion agent to think about next steps
    if next_suggestion is None:
        try:
            import asyncio

            from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
            from urika.agents.registry import AgentRegistry

            runner = ClaudeSDKRunner()
            registry = AgentRegistry()
            registry.discover()
            suggest_role = registry.get("advisor_agent")

            if suggest_role is not None:
                context = (
                    f"Project: {project_name}\n"
                    f"Completed experiments: {len(completed)}\n"
                    f"{methods_summary}\n{criteria_summary}\n"
                )
                if instructions:
                    context += f"\nUser instructions: {instructions}\n"
                context += "\nPropose the next experiment."

                config = suggest_role.build_config(
                    project_dir=project_path, experiment_id=""
                )

                from urika.cli_display import (
                    print_agent,
                    print_tool_use,
                )

                print_agent("advisor_agent")
                if panel is not None:
                    panel.update(agent="advisor_agent", activity="Analyzing…")

                def _on_msg(msg: object) -> None:
                    """Show tool use from suggestion agent."""
                    try:
                        model = getattr(msg, "model", None)
                        if model and panel is not None:
                            panel.set_model(model)
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
                                    if panel is not None:
                                        panel.set_thinking(tool_name)
                                else:
                                    if panel is not None:
                                        panel.set_thinking("Thinking…")
                    except Exception:
                        pass

                result = asyncio.run(runner.run(config, context, on_message=_on_msg))

                if result.success:
                    from urika.orchestrator.parsing import parse_suggestions

                    parsed = parse_suggestions(result.text_output)
                    if parsed and parsed.get("suggestions"):
                        next_suggestion = parsed["suggestions"][0]
                        click.echo(result.text_output.strip())
        except Exception:
            pass

    if next_suggestion is None:
        return None

    exp_name = next_suggestion.get("name", "auto-experiment").replace(" ", "-").lower()
    description = next_suggestion.get("method", next_suggestion.get("description", ""))
    if instructions:
        description = f"{instructions}\n\n{description}"

    # Show plan and confirm (unless --auto)
    print_step(f"Next experiment: {exp_name}")
    if description:
        short = description[:200] + "..." if len(description) > 200 else description
        click.echo(f"    {short}")
    if methods_summary:
        click.echo(f"    {methods_summary}")
    if criteria_summary:
        click.echo(f"    {criteria_summary}")

    if not auto:
        choice = _prompt_numbered(
            "\n  Proceed?",
            [
                "Yes — create and run it",
                "Different instructions",
                "Skip — exit",
            ],
            default=1,
        )

        if choice.startswith("Skip"):
            return None

        if choice.startswith("Different"):
            instructions = click.prompt("  Your instructions").strip()
            if instructions:
                description = f"{instructions}\n\n{description}"

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")
    return exp.experiment_id


@cli.command()
@click.argument("project")
@click.option(
    "--experiment", "experiment_id", default=None, help="Experiment ID to run."
)
@click.option("--max-turns", default=50, help="Maximum orchestrator turns.")
@click.option(
    "--continue",
    "resume",
    is_flag=True,
    default=False,
    help="Resume a paused or failed experiment.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress verbose tool-use streaming output.",
)
@click.option(
    "--auto",
    is_flag=True,
    default=False,
    help="Fully autonomous — no confirmation prompts.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the next experiment (e.g. 'focus on FOV-constrained models').",
)
def run(
    project: str,
    experiment_id: str | None,
    max_turns: int,
    resume: bool,
    quiet: bool,
    auto: bool,
    instructions: str,
) -> None:
    """Run an experiment using the orchestrator."""
    try:
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
    except ImportError:
        raise click.ClickException(
            "Claude Agent SDK not installed. Run: pip install urika[agents]"
        )
    import signal
    import time

    from urika.cli_display import (
        ThinkingPanel,
        print_agent,
        print_error,
        print_footer,
        print_header,
        print_step,
        print_success,
        print_tool_use,
        print_warning,
    )
    from urika.orchestrator import run_experiment

    from urika.cli_display import thinking_phrase

    project_path, _config = _resolve_project(project)

    # Show header immediately
    print_header(
        project_name=project,
        agent="orchestrator",
        mode=_config.mode,
    )

    # Create panel early so it's available during experiment selection
    panel = ThinkingPanel()
    panel.project = project
    panel.activity = thinking_phrase()
    panel.activate()
    panel.start_spinner()

    if experiment_id is None:
        experiments = list_experiments(project_path)
        # Find pending (non-completed) experiments
        pending = [
            e
            for e in experiments
            if load_progress(project_path, e.experiment_id).get("status")
            not in ("completed",)
        ]
        if pending:
            experiment_id = pending[-1].experiment_id
        else:
            # No pending — determine next experiment from state
            experiment_id = _determine_next_experiment(
                project_path,
                project,
                auto=auto,
                instructions=instructions,
                panel=panel,
            )
            if experiment_id is None:
                if not experiments:
                    raise click.ClickException(
                        "No experiments and no plan found. Create one with:\n"
                        f"  urika experiment create {project} <experiment-name>"
                    )
                experiment_id = experiments[-1].experiment_id
                print_step(f"All experiments completed. Re-running {experiment_id}")

    if resume:
        print_step(f"Resuming experiment {experiment_id}")
    else:
        print_step(f"Running experiment {experiment_id} (max {max_turns} turns)")

    # Register Ctrl+C handler to clean up lockfile
    def _cleanup_on_interrupt(signum: int, frame: object) -> None:
        print_warning("\nInterrupted — cleaning up...")
        try:
            from urika.core.session import fail_session

            fail_session(project_path, experiment_id, error="Interrupted by user")
        except Exception:
            # Force remove lockfile if fail_session fails
            lock = project_path / "experiments" / experiment_id / ".lock"
            lock.unlink(missing_ok=True)
        print_step("Experiment paused. Resume with: urika run --continue")
        raise SystemExit(1)

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _cleanup_on_interrupt)

    start_ms = int(time.monotonic() * 1000)

    sdk_runner = ClaudeSDKRunner()

    # Panel already created and active from experiment selection above
    try:

        def _on_progress(event: str, detail: str = "") -> None:
            if event == "turn":
                print_step(detail)
                panel.update(turn=detail, activity=thinking_phrase())
            elif event == "agent":
                # Extract agent key from "Planning agent — designing method"
                agent_key = detail.split("—")[0].strip().lower().replace(" ", "_")
                print_agent(agent_key)
                panel.update(agent=agent_key, activity=detail)
            elif event == "result":
                print_success(detail)
            elif event == "phase":
                print_step(detail)
                panel.update(activity=detail)

        def _on_message(msg: object) -> None:
            """Handle streaming SDK messages for verbose output."""
            # Capture model name from AssistantMessage
            model = getattr(msg, "model", None)
            if model:
                panel.set_model(model)

            # Use getattr for safe access — SDK types may vary
            content = getattr(msg, "content", None)
            if content is None:
                return
            for block in content:
                tool_name = getattr(block, "name", None) or getattr(
                    block, "tool_name", None
                )
                if tool_name:
                    detail = ""
                    input_data = getattr(block, "input", None) or getattr(
                        block, "tool_input", {}
                    )
                    if isinstance(input_data, dict):
                        if "command" in input_data:
                            detail = input_data["command"]
                        elif "file_path" in input_data:
                            detail = input_data["file_path"]
                        elif "pattern" in input_data:
                            detail = input_data["pattern"]
                    if not quiet:
                        print_tool_use(tool_name, detail)
                    panel.set_thinking(tool_name)
                else:
                    # Text block — agent is thinking
                    panel.set_thinking("Thinking…")

        result = asyncio.run(
            run_experiment(
                project_path,
                experiment_id,
                sdk_runner,
                max_turns=max_turns,
                resume=resume,
                on_progress=_on_progress,
                on_message=_on_message,
                instructions=instructions,
            )
        )

    finally:
        panel.cleanup()

    # Restore original handler
    signal.signal(signal.SIGINT, original_handler)

    elapsed_ms = int(time.monotonic() * 1000) - start_ms
    run_status = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    if run_status == "completed":
        print_success(f"Experiment completed after {turns} turns.")
    elif run_status == "failed":
        print_error(f"Experiment failed after {turns} turns: {error}")
    else:
        print_step(f"Experiment finished with status: {run_status} ({turns} turns)")

    print_footer(duration_ms=elapsed_ms, turns=turns, status=run_status)


@cli.command()
@click.argument("project")
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Generate report for a specific experiment.",
)
def report(project: str, experiment_id: str | None) -> None:
    """Generate labbook reports."""
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )

    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        try:
            update_experiment_notes(project_path, experiment_id)
            generate_experiment_summary(project_path, experiment_id)
        except FileNotFoundError:
            raise click.ClickException(f"Experiment '{experiment_id}' not found.")
        notes = project_path / "experiments" / experiment_id / "labbook" / "notes.md"
        summary = (
            project_path / "experiments" / experiment_id / "labbook" / "summary.md"
        )
        click.echo(f"Updated: {notes}")
        click.echo(f"Generated: {summary}")
        return

    # Project-level reports
    try:
        generate_results_summary(project_path)
        generate_key_findings(project_path)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc))

    # Also refresh notes for all experiments
    for exp in list_experiments(project_path):
        try:
            update_experiment_notes(project_path, exp.experiment_id)
        except FileNotFoundError:
            pass

    results_path = project_path / "projectbook" / "results-summary.md"
    findings_path = project_path / "projectbook" / "key-findings.md"
    click.echo(f"Generated: {results_path}")
    click.echo(f"Generated: {findings_path}")


@cli.command()
@click.argument("project")
@click.option(
    "--data", "data_file", default=None, help="Specific data file to inspect."
)
def inspect(project: str, data_file: str | None) -> None:
    """Inspect project data: schema, dtypes, missing values, preview."""
    from urika.data.loader import load_dataset

    project_path, config = _resolve_project(project)

    # Find data file
    if data_file is not None:
        path = (
            Path(data_file)
            if Path(data_file).is_absolute()
            else project_path / data_file
        )
    else:
        # Look for data files in project's data/ directory
        data_dir = project_path / "data"
        if not data_dir.exists():
            raise click.ClickException("No data/ directory found.")
        csv_files = list(data_dir.glob("*.csv"))
        if not csv_files:
            raise click.ClickException("No CSV files found in data/ directory.")
        path = csv_files[0]
        if len(csv_files) > 1:
            click.echo(f"Multiple data files found. Using: {path.name}")

    try:
        view = load_dataset(path)
    except Exception as exc:
        raise click.ClickException(f"Failed to load data: {exc}")

    click.echo(f"Dataset: {path.name}")
    click.echo(f"Rows: {view.summary.n_rows}")
    click.echo(f"Columns: {view.summary.n_columns}")
    click.echo("")

    # Schema table
    click.echo("Schema:")
    for col in view.summary.columns:
        dtype = view.summary.dtypes.get(col, "unknown")
        missing = view.summary.missing_counts.get(col, 0)
        missing_pct = (
            f" ({100 * missing / view.summary.n_rows:.1f}% missing)"
            if missing > 0
            else ""
        )
        click.echo(f"  {col:<30s} {dtype:<15s}{missing_pct}")
    click.echo("")

    # Preview (first 5 rows)
    click.echo("Preview (first 5 rows):")
    click.echo(view.data.head().to_string(index=False))


@cli.command()
@click.argument("project")
@click.option(
    "--experiment", "experiment_id", default=None, help="Specific experiment."
)
def logs(project: str, experiment_id: str | None) -> None:
    """Show experiment run log."""
    from urika.core.session import load_session

    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments in this project.")
        experiment_id = experiments[-1].experiment_id

    progress = load_progress(project_path, experiment_id)
    session = load_session(project_path, experiment_id)

    click.echo(f"Experiment: {experiment_id}")
    if session is not None:
        click.echo(f"Status: {session.status}")
        click.echo(f"Turns: {session.current_turn}")
    click.echo("")

    runs = progress.get("runs", [])
    if not runs:
        click.echo("No runs recorded yet.")
        return

    for run in runs:
        metrics_str = ", ".join(f"{k}={v}" for k, v in run.get("metrics", {}).items())
        click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
        if run.get("hypothesis"):
            click.echo(f"    Hypothesis: {run['hypothesis']}")
        if run.get("observation"):
            click.echo(f"    Observation: {run['observation']}")
        if run.get("next_step"):
            click.echo(f"    Next step: {run['next_step']}")
        click.echo("")


@cli.group()
def knowledge() -> None:
    """Manage project knowledge base."""


@knowledge.command("ingest")
@click.argument("project")
@click.argument("source")
def knowledge_ingest(project: str, source: str) -> None:
    """Ingest a file or URL into the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    try:
        entry = store.ingest(source)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc))
    click.echo(f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})')


@knowledge.command("search")
@click.argument("project")
@click.argument("query")
def knowledge_search(project: str, query: str) -> None:
    """Search the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    results = store.search(query)

    if not results:
        click.echo("No results found.")
        return

    for entry in results:
        snippet = entry.content[:100].replace("\n", " ")
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]  {snippet}")


@knowledge.command("list")
@click.argument("project")
def knowledge_list(project: str) -> None:
    """List all knowledge entries."""
    from urika.knowledge import KnowledgeStore

    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    entries = store.list_all()

    if not entries:
        click.echo("No knowledge entries yet.")
        return

    for entry in entries:
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]")
