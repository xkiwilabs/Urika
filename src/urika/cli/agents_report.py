"""`urika report` command + _run_report_agent helper.

Split out of cli/agents.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``report``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import (
    _ensure_project,
    _make_on_message,
    _prompt_numbered,
    _resolve_project,
)
from urika.core.experiment import list_experiments
from urika.core.progress import load_progress


def _run_report_agent(
    project_path: Path,
    experiment_id: str,
    prompt: str,
    instructions: str = "",
    audience: str = "expert",
) -> str:
    """Run the report agent and return its text output."""
    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
        from urika.cli_display import Spinner, print_agent

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()

        role = registry.get("report_agent")
        if role is None:
            return ""

        print_agent("report_agent")
        config = role.build_config(
            project_dir=project_path, experiment_id=experiment_id, audience=audience
        )

        if instructions:
            prompt = f"User instructions: {instructions}\n\n{prompt}"

        with Spinner("Writing narrative"):
            result = asyncio.run(
                runner.run(config, prompt, on_message=_make_on_message())
            )

        if result.success and result.text_output:
            return result.text_output.strip()
        return ""
    except ImportError:
        return ""
    except Exception:
        return ""


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Generate report for a specific experiment.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the report (e.g. 'focus on feature importance findings').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "standard", "expert"]),
    default=None,
    help="Output audience level (default: standard).",
)
def report(
    project: str,
    experiment_id: str | None,
    instructions: str,
    json_output: bool = False,
    audience: str | None = None,
) -> None:
    """Generate labbook reports."""
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    # If no experiment specified, offer selection (like REPL's _pick_experiment)
    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            # No experiments — fall through to project-level reports
            experiment_id = "project"
        elif json_output:
            # JSON mode: default to most recent experiment
            experiment_id = experiments[-1].experiment_id
        else:
            import sys as _sys

            _tui_active = getattr(_sys.stdin, "_tui_bridge", False)
            if not _sys.stdin.isatty() and not _tui_active:
                # Non-TTY caller — same most-recent fallback as
                # ``--json``. Avoids the EOF→default fallthrough bug
                # class that auto-fired the advisor's experiments
                # from the dashboard chat in pre-v0.3.2.
                experiment_id = experiments[-1].experiment_id
            else:
                # Build numbered options — most recent first
                reversed_exps = list(reversed(experiments))
                options = []
                for exp in reversed_exps:
                    progress = load_progress(project_path, exp.experiment_id)
                    status = progress.get("status", "pending")
                    runs = len(progress.get("runs", []))
                    options.append(
                        f"{exp.experiment_id} [{status}, {runs} runs]"
                    )
                options.append("All experiments (generate for each)")
                options.append("Project level (one overarching report)")

                choice = _prompt_numbered(
                    "\nSelect experiment for report:", options, default=1
                )

                if choice.startswith("All"):
                    experiment_id = "all"
                elif choice.startswith("Project"):
                    experiment_id = "project"
                else:
                    experiment_id = choice.split(" [")[0]

    try:
        if experiment_id == "all":
            # Generate reports for each experiment
            for exp in list_experiments(project_path):
                click.echo(f"Processing {exp.experiment_id}...")
                try:
                    update_experiment_notes(project_path, exp.experiment_id)
                    generate_experiment_summary(project_path, exp.experiment_id)
                except FileNotFoundError:
                    pass
                narrative = _run_report_agent(
                    project_path,
                    exp.experiment_id,
                    f"Write a detailed narrative report for experiment {exp.experiment_id}.",
                    instructions=instructions,
                    audience=audience,
                )
                if narrative:
                    from urika.core.report_writer import write_versioned

                    narrative_path = (
                        project_path
                        / "experiments"
                        / exp.experiment_id
                        / "labbook"
                        / "narrative.md"
                    )
                    narrative_path.parent.mkdir(parents=True, exist_ok=True)
                    write_versioned(narrative_path, narrative + "\n")
                    if not json_output:
                        click.echo(f"Generated: {narrative_path}")
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"output": "All experiment reports generated."})
                return
            click.echo("All experiment reports generated.")
            return

        if experiment_id == "project":
            # Project-level reports
            from urika.core.readme_generator import write_readme

            try:
                generate_results_summary(project_path)
                generate_key_findings(project_path)
                write_readme(project_path)
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
            readme_path = project_path / "README.md"

            # Call report agent for project-level narrative
            narrative = _run_report_agent(
                project_path,
                "",
                "Write a project-level narrative report covering all experiments "
                "and the research progression.",
                instructions=instructions,
                audience=audience,
            )
            if narrative:
                from urika.core.report_writer import write_versioned

                narrative_path = project_path / "projectbook" / "narrative.md"
                narrative_path.parent.mkdir(parents=True, exist_ok=True)
                write_versioned(narrative_path, narrative + "\n")

            if json_output:
                from urika.cli_helpers import output_json

                output_json(
                    {
                        "output": "Project-level reports generated.",
                        "path": str(results_path),
                    }
                )
                return

            click.echo(f"Generated: {results_path}")
            click.echo(f"Generated: {findings_path}")
            click.echo(f"Generated: {readme_path}")
            if narrative:
                click.echo(f"Generated: {narrative_path}")
            return

        # Single experiment report
        try:
            update_experiment_notes(project_path, experiment_id)
            generate_experiment_summary(project_path, experiment_id)
        except FileNotFoundError:
            raise click.ClickException(f"Experiment '{experiment_id}' not found.")
        notes = project_path / "experiments" / experiment_id / "labbook" / "notes.md"
        summary = (
            project_path / "experiments" / experiment_id / "labbook" / "summary.md"
        )

        # Call report agent to write narrative (like REPL)
        narrative = _run_report_agent(
            project_path,
            experiment_id,
            f"Write a detailed narrative report for experiment {experiment_id}.",
            instructions=instructions,
            audience=audience,
        )
        if narrative:
            from urika.core.report_writer import write_versioned

            narrative_path = (
                project_path
                / "experiments"
                / experiment_id
                / "labbook"
                / "narrative.md"
            )
            narrative_path.parent.mkdir(parents=True, exist_ok=True)
            write_versioned(narrative_path, narrative + "\n")

        if json_output:
            from urika.cli_helpers import output_json

            output_json(
                {
                    "output": f"Report generated for {experiment_id}.",
                    "path": str(summary),
                }
            )
            return

        click.echo(f"Updated: {notes}")
        click.echo(f"Generated: {summary}")
        if narrative:
            click.echo(f"Generated: {narrative_path}")
    except KeyboardInterrupt:
        click.echo("\n  Report generation stopped.")
        click.echo("  Re-run with: urika report [--instructions '...']")
