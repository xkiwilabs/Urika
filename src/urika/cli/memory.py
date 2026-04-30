"""``urika memory`` group — list / show / add / delete entries.

v0.4 Track 2 (Phase 1). Manual surface over the project memory
implemented in ``urika.core.project_memory``. Auto-capture is the
default — these commands are the safety valve for editing what the
agents captured.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import _ensure_project, _resolve_project


_VALID_TYPES = ("user", "feedback", "instruction", "decision", "reference")


@cli.group()
def memory() -> None:
    """List or edit project memory entries."""


@memory.command("list")
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def memory_list(project: str | None, json_output: bool) -> None:
    """List every memory entry in the project."""
    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    from urika.core.project_memory import list_entries, memory_dir

    rows = list_entries(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"project": name, "entries": rows, "memory_dir": str(memory_dir(project_path))})
        return

    if not rows:
        click.echo(f"No memory entries for project {name}.")
        click.echo(
            f"  (memory dir: {memory_dir(project_path)})"
        )
        return

    click.echo(f"Memory entries for {name}:")
    for r in rows:
        click.echo(
            f"  [{r['type']}] {r['filename']} — {r['description']}"
        )


@memory.command("show")
@click.argument("project", required=False, default=None)
@click.argument("topic")
def memory_show(project: str | None, topic: str) -> None:
    """Print a memory entry by filename or slug."""
    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    from urika.core.project_memory import memory_dir

    d = memory_dir(project_path)
    candidates = [
        d / topic,
        d / f"{topic}.md",
    ]
    # Allow a partial match — e.g. ``urika memory show feedback_methods``
    # finds ``feedback_methods.md`` or ``feedback_methods_v2.md``.
    if d.is_dir():
        candidates.extend(sorted(d.glob(f"{topic}*.md")))
    for path in candidates:
        if path.exists() and path.is_file():
            click.echo(path.read_text(encoding="utf-8"))
            return

    raise click.ClickException(
        f"No memory entry matching {topic!r} in {d}."
    )


@memory.command("add")
@click.argument("project", required=False, default=None)
@click.argument("topic")
@click.option(
    "--type",
    "mem_type",
    type=click.Choice(_VALID_TYPES),
    default="instruction",
    help="Memory type. Default: instruction.",
)
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    default=None,
    help="Read body from this file.",
)
@click.option(
    "--stdin",
    "use_stdin",
    is_flag=True,
    help="Read body from stdin (for piping).",
)
@click.option(
    "--description",
    "description",
    default="",
    help="One-line description for the index.",
)
def memory_add(
    project: str | None,
    topic: str,
    mem_type: str,
    from_file: str | None,
    use_stdin: bool,
    description: str,
) -> None:
    """Add a memory entry. Body may come from --from-file, --stdin,
    or an interactive editor."""
    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    if from_file and use_stdin:
        raise click.ClickException("Pass --from-file OR --stdin, not both.")

    if from_file:
        body = Path(from_file).read_text(encoding="utf-8")
    elif use_stdin:
        body = sys.stdin.read()
    else:
        body = click.edit(text="# Memory body\n\n", extension=".md") or ""
        if not body.strip():
            raise click.ClickException("Aborted — empty body.")

    from urika.core.project_memory import save_entry

    path = save_entry(
        project_path,
        mem_type=mem_type,
        body=body,
        description=description,
        slug=topic,
    )
    click.echo(f"  Wrote {path}")


@memory.command("delete")
@click.argument("project", required=False, default=None)
@click.argument("filename")
@click.option("--force", is_flag=True, help="Skip confirmation.")
def memory_delete(
    project: str | None, filename: str, force: bool
) -> None:
    """Trash a memory entry by filename. Trashes to memory/.trash/."""
    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    if not force:
        click.confirm(
            f"  Trash memory entry {filename!r}?",
            abort=True,
            default=False,
        )

    from urika.core.project_memory import delete_entry

    if delete_entry(project_path, filename):
        click.echo(f"  Trashed {filename}.")
    else:
        raise click.ClickException(f"No entry found at {filename!r}.")
