"""`urika present` command.

Split out of cli/agents.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``present``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import click

from urika.cli._base import cli
from urika.cli._helpers import (
    _agent_run_start,
    _ensure_project,
    _make_on_message,
    _prompt_numbered,
    _resolve_project,
)
from urika.core.errors import ConfigError
from urika.core.experiment import list_experiments
from urika.core.progress import load_progress


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Experiment ID (skips interactive prompt). Use 'project' for project-level, 'all' for every experiment.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the presentation (e.g. 'emphasize ensemble results').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "standard", "expert"]),
    default=None,
    help="Output audience level (default: standard).",
)
def present(
    project: str | None,
    experiment_id: str | None,
    instructions: str,
    json_output: bool,
    audience: str | None = None,
) -> None:
    """Generate a presentation for an experiment."""
    from urika.cli_display import Spinner, print_agent, print_success

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    experiments = list_experiments(project_path)
    if not experiments:
        raise click.ClickException("No experiments.")

    try:
        from urika.agents.runner import get_runner
        from urika.orchestrator.loop import _generate_presentation, _noop_callback
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
    on_msg = (lambda m: None) if json_output else _make_on_message()

    if experiment_id is not None:
        # Non-interactive selection — used by dashboard subprocess spawn.
        if experiment_id.lower() == "all":
            choice = "All experiments (generate for each)"
        elif experiment_id.lower() == "project":
            choice = "Project level (one overarching presentation)"
        else:
            valid_ids = {e.experiment_id for e in experiments}
            if experiment_id not in valid_ids:
                raise click.ClickException(
                    f"Unknown experiment: {experiment_id}"
                )
            progress = load_progress(project_path, experiment_id)
            exp_status = progress.get("status", "pending")
            runs = len(progress.get("runs", []))
            choice = f"{experiment_id} [{exp_status}, {runs} runs]"
    elif json_output:
        # JSON mode: default to most recent experiment, no interactive prompt
        choice = f"{experiments[-1].experiment_id} [auto]"
    else:
        # Build options — most recent first, plus all/project choices
        reversed_exps = list(reversed(experiments))
        options = []
        for exp in reversed_exps:
            progress = load_progress(project_path, exp.experiment_id)
            exp_status = progress.get("status", "pending")
            runs = len(progress.get("runs", []))
            options.append(f"{exp.experiment_id} [{exp_status}, {runs} runs]")
        options.append("All experiments (generate for each)")
        options.append("Project level (one overarching presentation)")

        choice = _prompt_numbered("\n  Select:", options, default=1)

    _start_ms, _start_iso = _agent_run_start()
    _pres_tokens_in = 0
    _pres_tokens_out = 0
    _pres_cost = 0.0
    _pres_calls = 0

    try:
        if choice.startswith("All"):
            # Generate presentation for each experiment
            for exp in experiments:
                if not json_output:
                    print_agent("presentation_agent")
                with Spinner("Creating slides"):
                    _pu = asyncio.run(
                        _generate_presentation(
                            project_path,
                            exp.experiment_id,
                            runner,
                            _noop_callback,
                            on_message=on_msg,
                            instructions=instructions,
                            audience=audience,
                        )
                    )
                    _pres_tokens_in += _pu.get("tokens_in", 0)
                    _pres_tokens_out += _pu.get("tokens_out", 0)
                    _pres_cost += _pu.get("cost_usd", 0.0)
                    _pres_calls += _pu.get("agent_calls", 0)
                if not json_output:
                    print_success(
                        f"Saved to experiments/{exp.experiment_id}/presentation/index.html"
                    )
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(project_path / "experiments")})
                return
            print_success("All presentations generated")
        elif choice.startswith("Project"):
            # Project-level presentation
            if not json_output:
                print_agent("presentation_agent")
            with Spinner("Creating slides"):
                _pu = asyncio.run(
                    _generate_presentation(
                        project_path,
                        "",
                        runner,
                        _noop_callback,
                        on_message=on_msg,
                        instructions=instructions,
                        audience=audience,
                    )
                )
                _pres_tokens_in += _pu.get("tokens_in", 0)
                _pres_tokens_out += _pu.get("tokens_out", 0)
                _pres_cost += _pu.get("cost_usd", 0.0)
                _pres_calls += _pu.get("agent_calls", 0)
            pres_path = project_path / "projectbook" / "presentation" / "index.html"
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(pres_path)})
                return
            print_success("Saved to projectbook/presentation/index.html")
        else:
            # Single experiment
            exp_id = choice.split(" [")[0]
            if not json_output:
                print_agent("presentation_agent")
            with Spinner("Creating slides"):
                _pu = asyncio.run(
                    _generate_presentation(
                        project_path,
                        exp_id,
                        runner,
                        _noop_callback,
                        on_message=on_msg,
                        instructions=instructions,
                        audience=audience,
                    )
                )
                _pres_tokens_in += _pu.get("tokens_in", 0)
                _pres_tokens_out += _pu.get("tokens_out", 0)
                _pres_cost += _pu.get("cost_usd", 0.0)
                _pres_calls += _pu.get("agent_calls", 0)
            pres_path = (
                project_path / "experiments" / exp_id / "presentation" / "index.html"
            )
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(pres_path)})
                return
            print_success(f"Saved to experiments/{exp_id}/presentation/index.html")
    except KeyboardInterrupt:
        click.echo("\n  Presentation stopped.")
        click.echo("  Re-run with: urika present [--instructions '...']")

    # Record presentation usage
    try:
        from urika.core.usage import record_session

        _elapsed_ms = int(time.monotonic() * 1000) - _start_ms
        record_session(
            project_path,
            started=_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=_elapsed_ms,
            tokens_in=_pres_tokens_in,
            tokens_out=_pres_tokens_out,
            cost_usd=_pres_cost,
            agent_calls=_pres_calls,
            experiments_run=0,
        )
    except Exception:
        pass
