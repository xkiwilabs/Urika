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
    from urika.core.project_builder import ProjectBuilder

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

    source = Path(data_path) if data_path else _projects_dir() / name
    builder = ProjectBuilder(
        name=name,
        source_path=source,
        projects_dir=_projects_dir(),
        description=description or "",
        question=question,
        mode=mode,
    )

    if data_path:
        builder.source_path = Path(data_path)

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

    # Scan and profile if a data path was provided
    scan_result = None
    data_summary = None
    if data_path:
        scan_result = builder.scan()
        click.echo(scan_result.summary())

        # Offer to ingest docs/papers into knowledge base
        has_knowledge = bool(scan_result.docs or scan_result.papers or scan_result.code)

        try:
            data_summary = builder.profile_data()
            click.echo(
                f"\nData profile: {data_summary.n_rows} rows,"
                f" {data_summary.n_columns} columns"
            )
        except (ValueError, Exception):
            pass  # No readable data files — continue without profile

    # --- Interactive agent loop ---
    click.echo("\nStarting interactive project scoping...\n")
    try:
        _run_builder_agent_loop(
            builder, scan_result, data_summary, description or "", question
        )
    except Exception as exc:
        click.echo(f"\nAgent loop unavailable ({exc}). Continuing with manual setup.")

    project_dir = builder.write_project()

    # Ingest knowledge if available
    if data_path and scan_result and has_knowledge:
        ingest = click.confirm(
            "Ingest documentation and papers into the knowledge base?", default=True
        )
        if ingest:
            _ingest_knowledge(project_dir, scan_result)

    registry = ProjectRegistry()
    registry.register(name, project_dir)

    click.echo(f"\nCreated project '{name}' at {project_dir}")


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
    from urika.core.builder_prompts import (
        build_planning_prompt,
        build_scoping_prompt,
        build_suggestion_prompt,
    )
    from urika.orchestrator.parsing import (
        _extract_json_blocks,
        parse_suggestions,
    )

    runner = ClaudeSDKRunner()
    registry = AgentRegistry()
    registry.discover()

    # --- Phase 1: Clarifying questions ---
    builder_role = registry.get("project_builder")
    if builder_role is None:
        click.echo("Project builder agent not found. Skipping interactive scoping.")
        return

    if scan_result is None:
        click.echo("No data scanned. Skipping interactive scoping.")
        return

    answers: dict[str, str] = {}
    context = ""
    max_questions = 5

    click.echo("The project builder will ask a few questions to scope the project.\n")

    for i in range(max_questions):
        prompt = build_scoping_prompt(scan_result, data_summary, description, context)
        config = builder_role.build_config(project_dir=builder.source_path)
        result = asyncio.run(runner.run(config, prompt))

        if not result.success:
            click.echo(f"Agent error: {result.error}")
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
            # Fallback: use raw text output as the question
            question_text = result.text_output.strip()
            if not question_text:
                break
            click.echo(f"\n{question_text}")

        answer = click.prompt("\nYour answer (or 'done' to move on)").strip()
        if answer.lower() == "done":
            break

        answers[question_text] = answer
        context += f"Q: {question_text}\nA: {answer}\n\n"

    # --- Phase 2: Suggestion agent ---
    click.echo("\nGenerating initial suggestions...\n")
    suggest_role = registry.get("suggestion_agent")
    if suggest_role is None:
        click.echo("Suggestion agent not found. Skipping.")
        return

    suggest_prompt = build_suggestion_prompt(description, data_summary, answers)
    suggest_config = suggest_role.build_config(
        project_dir=builder.source_path, experiment_id=""
    )
    suggest_result = asyncio.run(runner.run(suggest_config, suggest_prompt))

    if not suggest_result.success:
        click.echo(f"Suggestion agent error: {suggest_result.error}")
        return

    suggestions = parse_suggestions(suggest_result.text_output)
    click.echo(suggest_result.text_output.strip())

    # --- Phase 3: Planning agent ---
    click.echo("\nGenerating initial plan...\n")
    plan_role = registry.get("planning_agent")
    if plan_role is None:
        click.echo("Planning agent not found. Skipping.")
        if suggestions:
            builder.set_initial_suggestions(suggestions)
        return

    plan_prompt = build_planning_prompt(suggestions or {}, description, data_summary)
    plan_config = plan_role.build_config(
        project_dir=builder.source_path, experiment_id=""
    )
    plan_result = asyncio.run(runner.run(plan_config, plan_prompt))

    if not plan_result.success:
        click.echo(f"Planning agent error: {plan_result.error}")
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
        # Refine
        refinement = click.prompt("Your suggestions").strip()
        if not refinement:
            continue

        # Re-run suggestion + planning with refinement
        click.echo("\nRefining plan...\n")
        refined_prompt = suggest_prompt + f"\n\n## User Refinement\n{refinement}"
        suggest_result = asyncio.run(runner.run(suggest_config, refined_prompt))
        if suggest_result.success:
            suggestions = parse_suggestions(suggest_result.text_output)
            plan_prompt = build_planning_prompt(
                suggestions or {}, description, data_summary
            )
            plan_result = asyncio.run(runner.run(plan_config, plan_prompt))
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
def run(project: str, experiment_id: str | None, max_turns: int, resume: bool) -> None:
    """Run an experiment using the orchestrator."""
    from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
    from urika.orchestrator import run_experiment

    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException(
                "No experiments in this project. Create one first."
            )
        experiment_id = experiments[-1].experiment_id
        click.echo(f"Using latest experiment: {experiment_id}")

    if resume:
        click.echo(f"Resuming experiment {experiment_id}...")
    else:
        click.echo(f"Running experiment {experiment_id} (max {max_turns} turns)...")

    sdk_runner = ClaudeSDKRunner()
    result = asyncio.run(
        run_experiment(
            project_path,
            experiment_id,
            sdk_runner,
            max_turns=max_turns,
            resume=resume,
        )
    )

    run_status = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    if run_status == "completed":
        click.echo(f"Experiment completed after {turns} turns.")
    elif run_status == "failed":
        click.echo(f"Experiment failed after {turns} turns: {error}")
    else:
        click.echo(f"Experiment finished with status: {run_status} ({turns} turns)")


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

    results_path = project_path / "labbook" / "results-summary.md"
    findings_path = project_path / "labbook" / "key-findings.md"
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
