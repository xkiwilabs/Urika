"""Data/results-related CLI commands: results, methods, tools, logs, usage, knowledge, experiment, venv."""

from __future__ import annotations


import click

from urika.cli._base import cli
from urika.core.experiment import create_experiment, list_experiments
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.evaluation.leaderboard import load_leaderboard
from urika.tools import ToolRegistry

from urika.cli._helpers import (
    _resolve_project,
    _ensure_project,
    _prompt_numbered,
)


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Show runs for a specific experiment.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def results(project: str, experiment_id: str | None, json_output: bool) -> None:
    """Show project results (leaderboard or experiment runs)."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        progress = load_progress(project_path, experiment_id)
        runs = progress.get("runs", [])
        if json_output:
            from urika.cli_helpers import output_json

            output_json({"runs": runs})
            return
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

    # Count actual runs across all experiments so we can flag the
    # leaderboard-vs-run-count discrepancy when it would otherwise
    # confuse the user. The leaderboard keeps best-per-method, so a
    # run that doesn't improve any method's best is silently
    # dropped from the ranking. Pre-fix this surfaced as ``urika
    # status`` reporting "8 runs" while ``urika results`` listed
    # only 7 with no explanation — reported by Cathy on Windows.
    total_runs = 0
    for exp in list_experiments(project_path):
        progress = load_progress(project_path, exp.experiment_id)
        total_runs += len(progress.get("runs", []))

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "ranking": ranking,
                "total_runs": total_runs,
                "ranked_runs": len(ranking),
            }
        )
        return

    if not ranking:
        click.echo("No results yet.")
        return

    for entry in ranking:
        metrics_str = ", ".join(f"{k}={v}" for k, v in entry.get("metrics", {}).items())
        click.echo(f"  #{entry['rank']}  {entry['method']}  {metrics_str}")

    if total_runs > len(ranking):
        diff = total_runs - len(ranking)
        word = "run" if diff == 1 else "runs"
        click.echo("")
        click.echo(
            f"  Showing {len(ranking)} of {total_runs} runs "
            f"(leaderboard keeps best-per-method; "
            f"{diff} {word} below their method's best are hidden — "
            f"use 'urika results --experiment <id>' to see all)."
        )


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def methods(project: str, json_output: bool) -> None:
    """List agent-created methods in a project."""
    from urika.core.method_registry import load_methods

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    method_list = load_methods(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"methods": method_list})
        return

    if not method_list:
        click.echo("No methods created yet.")
        return

    for m in method_list:
        metrics = m.get("metrics", {})
        nums = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        metric_str = ", ".join(f"{k}={v}" for k, v in list(nums.items())[:2])
        click.echo(f"  {m['name']}  [{m.get('status', '')}]  {metric_str}")


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific tools.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def tools(category: str | None, project: str | None, json_output: bool) -> None:
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

    if json_output:
        from urika.cli_helpers import output_json

        tools_data = []
        for name in names:
            tool = registry.get(name)
            if tool is not None:
                tools_data.append(
                    {
                        "name": tool.name(),
                        "category": tool.category(),
                        "description": tool.description(),
                    }
                )
        output_json({"tools": tools_data})
        return

    if not names:
        click.echo("No tools found.")
        return

    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"  {tool.name()}  [{tool.category()}]  {tool.description()}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment", "experiment_id", default=None, help="Specific experiment."
)
@click.option(
    "--summary",
    is_flag=True,
    default=False,
    help=(
        "Show progress.json run summary instead of the raw log. Pre-v0.4.2 "
        "this was the only behaviour and the docstring lied: 'urika logs' "
        "never opened run.log. The dashboard's log view always tailed the "
        "real log; the CLI now matches."
    ),
)
@click.option(
    "--tail",
    type=int,
    default=50,
    help="Lines of run.log to print (default: 50). Ignored under --summary.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def logs(
    project: str,
    experiment_id: str | None,
    summary: bool,
    tail: int,
    json_output: bool,
) -> None:
    """Tail an experiment's run.log (or print the run summary with --summary)."""
    from urika.core.session import load_session

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            # v0.4: a fresh project with no experiments is normal
            # state, not an error. JSON mode returns an empty
            # logs array; human mode prints a friendly message
            # and exits zero so scripts can `if urika logs ...;
            # then` without trapping non-zero on empty.
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"project": project, "logs": []})
                return
            click.echo(f"No experiments in {project} yet.")
            return
        if len(experiments) == 1:
            experiment_id = experiments[0].experiment_id
        else:
            if json_output:
                # Default to most recent experiment for JSON mode
                experiment_id = experiments[-1].experiment_id
            else:
                # Offer selection when multiple experiments exist
                reversed_exps = list(reversed(experiments))
                options = []
                for exp in reversed_exps:
                    progress_data = load_progress(project_path, exp.experiment_id)
                    status = progress_data.get("status", "pending")
                    runs = len(progress_data.get("runs", []))
                    options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
                choice = _prompt_numbered(
                    "\nSelect experiment to view logs:", options, default=1
                )
                experiment_id = choice.split(" [")[0]

    progress = load_progress(project_path, experiment_id)
    session = load_session(project_path, experiment_id)
    log_path = project_path / "experiments" / experiment_id / "run.log"

    if json_output:
        from urika.cli_helpers import output_json

        runs = progress.get("runs", [])
        data: dict[str, object] = {
            "experiment_id": experiment_id,
            "runs": runs,
        }
        if session is not None:
            data["status"] = session.status
            data["turns"] = session.current_turn
        # Include the requested tail of run.log under the new "log_lines"
        # key so JSON consumers get the actual log without parsing the
        # progress summary. Empty list when the log doesn't exist.
        data["log_path"] = str(log_path)
        if log_path.exists():
            try:
                lines = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                data["log_lines"] = lines[-tail:] if tail > 0 else lines
            except OSError as exc:
                data["log_lines"] = []
                data["log_error"] = str(exc)
        else:
            data["log_lines"] = []
        output_json(data)
        return

    if summary:
        # Legacy behaviour — progress.json summary, kept for users who
        # scripted against pre-v0.4.2 output. New default is the log tail.
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
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in run.get("metrics", {}).items()
            )
            click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
            if run.get("hypothesis"):
                click.echo(f"    Hypothesis: {run['hypothesis']}")
            if run.get("observation"):
                click.echo(f"    Observation: {run['observation']}")
            if run.get("next_step"):
                click.echo(f"    Next step: {run['next_step']}")
            click.echo("")
        return

    # Default: tail run.log (the file the dashboard's log view shows).
    if not log_path.exists():
        click.echo(
            f"No run.log yet at {log_path}. "
            f"Run the experiment first or pass --summary for the progress view.",
            err=True,
        )
        # Exit zero so scripts can pipe without trapping; absence is a
        # legitimate state on a never-run experiment.
        return

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        click.echo(f"Failed to read {log_path}: {exc}", err=True)
        raise SystemExit(1) from exc

    selected = lines[-tail:] if tail > 0 else lines
    for line in selected:
        click.echo(line)


@cli.group()
def knowledge() -> None:
    """Manage project knowledge base."""


@knowledge.command("ingest")
@click.argument("project", required=False, default=None)
@click.argument("source")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_ingest(project: str, source: str, json_output: bool) -> None:
    """Ingest a file or URL into the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    try:
        entry = store.ingest(source)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc))

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"id": entry.id, "title": entry.title, "source_type": entry.source_type}
        )
        return

    click.echo(f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})')


@knowledge.command("search")
@click.argument("project", required=False, default=None)
@click.argument("query")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_search(project: str, query: str, json_output: bool) -> None:
    """Search the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    results_list = store.search(query)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "results": [
                    {
                        "id": e.id,
                        "title": e.title,
                        "source_type": e.source_type,
                        "snippet": e.content[:200],
                    }
                    for e in results_list
                ]
            }
        )
        return

    if not results_list:
        click.echo("No results found.")
        return

    for entry in results_list:
        snippet = entry.content[:100].replace("\n", " ")
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]  {snippet}")


@knowledge.command("list")
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_list(project: str, json_output: bool) -> None:
    """List all knowledge entries."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    entries = store.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "entries": [
                    {"id": e.id, "title": e.title, "source_type": e.source_type}
                    for e in entries
                ]
            }
        )
        return

    if not entries:
        click.echo("No knowledge entries yet.")
        return

    for entry in entries:
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def usage(project: str | None, json_output: bool) -> None:
    """Show usage stats for a project."""
    from urika.core.usage import format_usage, get_last_session, get_totals

    if project:
        project = _ensure_project(project)
        project_path, _config = _resolve_project(project)
        last = get_last_session(project_path)
        totals = get_totals(project_path)

        if json_output:
            from urika.cli_helpers import output_json

            output_json({"session": last or {}, "total": totals})
            return

        click.echo(f"\n  Usage: {project}")
        click.echo(format_usage(last, totals))
    else:
        # All projects
        registry_obj = ProjectRegistry()
        projects = registry_obj.list_all()

        if json_output:
            from urika.cli_helpers import output_json

            all_usage = {}
            for name, path in projects.items():
                all_usage[name] = get_totals(path)
            output_json({"projects": all_usage})
            return

        if not projects:
            click.echo("  No projects.")
            return
        click.echo("\n  Usage across all projects:")
        for name, path in projects.items():
            totals = get_totals(path)
            if totals.get("sessions", 0) > 0:
                tokens = totals.get("total_tokens_in", 0) + totals.get(
                    "total_tokens_out", 0
                )
                tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
                click.echo(
                    f"  {name}: {totals['sessions']} sessions · "
                    f"{tok_str} tokens · ~${totals['total_cost_usd']:.2f}"
                )
    click.echo()


# ── Experiment subgroup ─────────────────────────────────────


@cli.group()
def experiment() -> None:
    """Manage experiments within a project."""


@experiment.command("create")
@click.argument("project", required=False, default=None)
@click.argument("name")
@click.option("--hypothesis", default="", help="Experiment hypothesis.")
def experiment_create(project: str, name: str, hypothesis: str) -> None:
    """Create a new experiment in a project."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    exp = create_experiment(project_path, name=name, hypothesis=hypothesis)
    click.echo(f"{exp.experiment_id}")


@experiment.command("list")
@click.argument("project", required=False, default=None)
def experiment_list(project: str) -> None:
    """List experiments in a project."""
    project = _ensure_project(project)
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


@experiment.command("delete")
@click.argument("project", required=False, default=None)
@click.argument("exp_id")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation prompt.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON result.")
def experiment_delete(
    project: str | None, exp_id: str, force: bool, json_output: bool
) -> None:
    """Move an experiment to <project>/trash/.

    The experiment directory is moved (not deleted) so artifacts are
    preserved. Empty the project's trash folder manually when you're
    sure.
    """
    from urika.core.experiment_delete import (
        ActiveExperimentError,
        ExperimentNotFoundError,
        trash_experiment,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if not force:
        try:
            click.confirm(
                f"Move experiment '{exp_id}' to {project_path}/trash/? "
                "(files preserved)",
                abort=True,
            )
        except click.Abort:
            click.echo("Aborted.")
            return

    try:
        result = trash_experiment(project_path, project, exp_id)
    except ExperimentNotFoundError:
        raise click.ClickException(
            f"Experiment '{exp_id}' not found in project '{project}'."
        )
    except ActiveExperimentError as e:
        raise click.ClickException(str(e))

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "project_name": result.project_name,
                "experiment_id": result.experiment_id,
                "original_path": str(result.original_path),
                "trash_path": str(result.trash_path),
            }
        )
        return

    click.echo(f"Moved '{exp_id}' to {result.trash_path}")


# ── Unlock command ──────────────────────────────────────────
#
# v0.4.2 Package K: provides a recovery path when an experiment's
# ``.lock`` file refers to a PID that's been recycled by the OS to an
# unrelated process. Pre-K the only ways to recover were (a) wait for
# the PID to die, or (b) manually delete the lock file. ``urika
# unlock`` is the documented, audit-friendly action.


@cli.command("unlock")
@click.argument("project", required=False, default=None)
@click.argument("experiment_id", required=False, default=None)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Skip the safety check and unlock even if the lock looks valid.",
)
def unlock(
    project: str | None,
    experiment_id: str | None,
    force: bool,
) -> None:
    """Clear a stale experiment lock so a fresh run can start.

    Safe by default: refuses to unlock if the PID in the lock file is
    alive AND its process name suggests it's a real Urika run. Use
    ``--force`` to override (e.g. for PID-recycle false positives the
    OS handed your old PID to a different program).
    """
    import re

    from urika.core.experiment import list_experiments
    from urika.core.session import (
        _get_process_name,
        _lock_path,
        _pid_is_alive,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        locked = [
            e for e in experiments if _lock_path(project_path, e.experiment_id).exists()
        ]
        if not locked:
            click.echo(f"  No locked experiments in {project}.")
            return
        if len(locked) == 1:
            experiment_id = locked[0].experiment_id
            click.echo(f"  Unlocking {experiment_id}...")
        else:
            options = [e.experiment_id for e in locked]
            choice = _prompt_numbered(
                "\n  Select experiment to unlock:", options, default=1
            )
            experiment_id = choice

    lock_path = _lock_path(project_path, experiment_id)
    if not lock_path.exists():
        click.echo(f"  No lock file at {lock_path}.")
        return

    pid_str = ""
    try:
        pid_str = lock_path.read_text().strip()
    except OSError as exc:
        click.echo(f"  Could not read lock file: {exc}", err=True)
        raise SystemExit(1) from exc

    pid_alive = False
    proc_name = ""
    if pid_str:
        try:
            pid = int(pid_str)
        except ValueError:
            pid = -1
        if pid > 0:
            pid_alive = _pid_is_alive(pid)
            if pid_alive:
                # Surface what the PID actually IS so the user can
                # decide whether it's a real Urika run vs a recycled-
                # PID false positive. Cross-platform via psutil; pre-
                # fix this read /proc/<pid>/comm and was Linux-only.
                proc_name = _get_process_name(pid)

    if pid_alive and not force:
        looks_like_urika = bool(re.search(r"urika|python", proc_name, re.I))
        click.echo(
            f"  Lock owner PID {pid_str} is ALIVE"
            + (f" (process: {proc_name})" if proc_name else "")
            + ".",
            err=True,
        )
        if looks_like_urika:
            click.echo(
                "  This looks like a real running Urika process.",
                err=True,
            )
            click.echo(
                f"  Refusing to unlock without --force. If you're sure "
                f"the PID is unrelated, run: urika unlock {project} "
                f"{experiment_id} --force",
                err=True,
            )
            raise SystemExit(1)
        else:
            click.echo(
                "  The PID does NOT look like Urika — likely a "
                "recycled PID. Pass --force to unlock anyway.",
                err=True,
            )
            raise SystemExit(1)

    try:
        lock_path.unlink()
        click.echo(f"  Unlocked {experiment_id}.")
    except OSError as exc:
        click.echo(f"  Failed to remove lock: {exc}", err=True)
        raise SystemExit(1) from exc


# ── Venv subgroup ───────────────────────────────────────────


@cli.group("venv")
def venv_group() -> None:
    """Manage project virtual environments."""


@venv_group.command("create")
@click.argument("project", required=False, default=None)
def venv_create(project: str | None) -> None:
    """Create a venv for a project."""
    import tomllib

    from urika.core.venv import create_project_venv

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    venv_path = create_project_venv(project_path)

    # Update urika.toml to enable venv
    toml_path = project_path / "urika.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    data.setdefault("environment", {})["venv"] = True
    from urika.core.workspace import _write_toml

    _write_toml(toml_path, data)

    click.echo(f"Created .venv at {venv_path}")


@venv_group.command("status")
@click.argument("project", required=False, default=None)
def venv_status(project: str | None) -> None:
    """Show venv status for a project."""
    from urika.core.venv import is_venv_enabled

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if is_venv_enabled(project_path):
        venv_path = project_path / ".venv"
        exists = venv_path.exists()
        click.echo(f"Venv: enabled ({'exists' if exists else 'NOT FOUND'})")
        click.echo(f"Path: {venv_path}")
    else:
        click.echo("Venv: not enabled (using global environment)")
