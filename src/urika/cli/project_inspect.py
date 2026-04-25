"""`urika update` and `urika inspect` commands.

Split out of cli/project.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorators for ``update`` and
``inspect``.
"""

from __future__ import annotations

from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import _ensure_project, _resolve_project


@cli.command("update")
@click.argument("project", required=False, default=None)
@click.option(
    "--field",
    type=click.Choice(
        ["description", "question", "mode"],
        case_sensitive=False,
    ),
    default=None,
    help="Field to update.",
)
@click.option("--value", default=None, help="New value.")
@click.option(
    "--reason",
    default="",
    help="Why this change was made.",
)
@click.option(
    "--history",
    is_flag=True,
    help="Show revision history.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def update_project(
    project: str | None,
    field: str | None,
    value: str | None,
    reason: str,
    history: bool,
    json_output: bool,
) -> None:
    """Update project description, question, or mode.

    Changes are versioned — previous values are preserved
    with timestamps in revisions.json.

    Examples:

        urika update my-study --field question --value "Does X predict Y?"

        urika update my-study --field description --reason "Added new variables"

        urika update my-study --history
    """
    from urika.cli_display import (
        print_step,
        print_success,
    )
    from urika.cli_helpers import interactive_numbered, interactive_prompt

    project = _ensure_project(project)
    project_path, config = _resolve_project(project)

    # Show history
    if history:
        from urika.core.revisions import load_revisions

        revs = load_revisions(project_path)

        if json_output:
            from urika.cli_helpers import output_json

            output_json({"revisions": revs})
            return

        if not revs:
            click.echo("  No revisions recorded.")
            return
        click.echo(f"\n  Revision history for {project}:\n")
        for r in revs:
            ts = r["timestamp"][:19].replace("T", " ")
            click.echo(f"  #{r['revision']}  {ts}  [{r['field']}]")
            click.echo(
                f"    Old: {r['old_value'][:80]}"
                f"{'…' if len(r['old_value']) > 80 else ''}"
            )
            click.echo(
                f"    New: {r['new_value'][:80]}"
                f"{'…' if len(r['new_value']) > 80 else ''}"
            )
            if r.get("reason"):
                click.echo(f"    Why: {r['reason']}")
            click.echo()
        return

    # JSON mode requires --field and --value
    if json_output and (field is None or value is None):
        from urika.cli_helpers import output_json_error

        output_json_error("--field and --value are required in --json mode")
        raise SystemExit(1)

    # Interactive if no field specified
    if field is None:
        click.echo(f"\n  Current project config for {project}:\n")
        click.echo(f"  Description: {config.description[:100]}")
        click.echo(f"  Question:    {config.question[:100]}")
        click.echo(f"  Mode:        {config.mode}")
        click.echo()
        field = interactive_numbered(
            "  Field to update:",
            ["description", "question", "mode"],
            default=1,
        )

    # Show current value and get new value
    current = getattr(config, field, "")
    if value is None:
        click.echo(f"\n  Current {field}:")
        click.echo(f"  {current}\n")
        if field == "mode":
            from urika.core.models import VALID_MODES

            value = interactive_numbered(
                f"  New {field}:",
                sorted(VALID_MODES),
                default=1,
            )
        else:
            value = interactive_prompt(f"New {field}", required=True)

    if not value:
        if json_output:
            from urika.cli_helpers import output_json_error

            output_json_error("No value provided.")
            raise SystemExit(1)
        click.echo("  No change.")
        return

    if value == current:
        if json_output:
            from urika.cli_helpers import output_json

            output_json({"unchanged": True, "field": field, "value": value})
            return
        click.echo("  Value unchanged.")
        return

    if not json_output and not reason:
        reason = interactive_prompt(
            "Reason for change (optional, Enter to skip)",
            default="",
        )

    from urika.core.revisions import update_project_field

    rev = update_project_field(
        project_path,
        field=field,
        new_value=value,
        reason=reason,
    )

    if json_output:
        from urika.cli_helpers import output_json

        output_json(rev)
        return

    print_success(f"Updated {field} (revision #{rev['revision']})")
    print_step("Previous value preserved in revisions.json")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--data", "data_file", default=None, help="Specific data file to inspect."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def inspect(project: str, data_file: str | None, json_output: bool) -> None:
    """Inspect project data: schema, dtypes, missing values, preview."""
    from urika.data.loader import load_dataset

    project = _ensure_project(project)
    project_path, config = _resolve_project(project)

    # Find data file
    if data_file is not None:
        path = (
            Path(data_file)
            if Path(data_file).is_absolute()
            else project_path / data_file
        )
    else:
        # Collect candidate directories: project data/ first, then
        # external paths from config.data_paths and [data].source.
        _supported_exts = (
            "*.csv",
            "*.tsv",
            "*.xlsx",
            "*.xls",
            "*.parquet",
            "*.json",
            "*.jsonl",
        )
        candidate_dirs: list[Path] = []
        data_dir = project_path / "data"
        if data_dir.exists():
            candidate_dirs.append(data_dir)
        # Fall back to configured external data paths
        for dp in config.data_paths:
            p = Path(dp)
            if p.exists() and p not in candidate_dirs:
                candidate_dirs.append(p)
        # Also check [data].source from urika.toml
        try:
            import tomllib

            toml_path = project_path / "urika.toml"
            if toml_path.exists():
                with open(toml_path, "rb") as _f:
                    _toml = tomllib.load(_f)
                _src = _toml.get("data", {}).get("source", "")
                if _src:
                    _src_path = Path(_src)
                    if _src_path.exists() and _src_path not in candidate_dirs:
                        candidate_dirs.append(_src_path)
        except Exception:
            pass

        if not candidate_dirs:
            if json_output:
                from urika.cli_helpers import output_json_error

                output_json_error("No data directory or configured data paths found.")
                raise SystemExit(1)
            raise click.ClickException(
                "No data directory or configured data paths found."
            )

        data_files: list[Path] = []
        for cdir in candidate_dirs:
            if cdir.is_file():
                data_files.append(cdir)
            else:
                for _ext in _supported_exts:
                    data_files.extend(cdir.glob(_ext))
                    # Also search subdirectories for the pattern
                    data_files.extend(cdir.glob(f"**/{_ext}"))
        # Deduplicate while preserving order
        seen: set[Path] = set()
        unique_files: list[Path] = []
        for f in data_files:
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique_files.append(f)
        data_files = unique_files

        if not data_files:
            if json_output:
                from urika.cli_helpers import output_json_error

                output_json_error("No supported data files found in data paths.")
                raise SystemExit(1)
            raise click.ClickException("No supported data files found in data paths.")
        path = data_files[0]
        if len(data_files) > 1 and not json_output:
            click.echo(
                f"Multiple data files found ({len(data_files)}). Using: {path.name}"
            )

    try:
        view = load_dataset(path)
    except Exception as exc:
        raise click.ClickException(f"Failed to load data: {exc}")

    if json_output:
        from urika.cli_helpers import output_json

        columns_data = []
        for col in view.summary.columns:
            columns_data.append(
                {
                    "name": col,
                    "dtype": view.summary.dtypes.get(col, "unknown"),
                    "missing": view.summary.missing_counts.get(col, 0),
                }
            )
        output_json(
            {
                "dataset": path.name,
                "rows": view.summary.n_rows,
                "columns": columns_data,
            }
        )
        return

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
