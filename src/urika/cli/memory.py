"""``urika memory`` group — list / show / add / delete entries.

v0.4 Track 2 (Phase 1). Manual surface over the project memory
implemented in ``urika.core.project_memory``. Auto-capture is the
default — these commands are the safety valve for editing what the
agents captured.
"""

from __future__ import annotations

import re as _re
import sys
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from datetime import timezone as _timezone
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import _ensure_project, _resolve_project


_VALID_TYPES = ("user", "feedback", "instruction", "decision", "reference")


def _parse_relative(s: str) -> _datetime:
    """Parse a timestamp argument for ``urika memory diff``.

    Accepts:

    * ``"now"``
    * ``"yesterday"``
    * ``"{N}{h|d|w} ago"`` — e.g. ``"3h ago"``, ``"2d ago"``, ``"1w ago"``.
      Underscores are also accepted in place of the space (``"1h_ago"``)
      so the REPL slash command can pass single-token arguments.
    * Anything else is fed to :meth:`datetime.fromisoformat` — raises
      ``ValueError`` on failure.
    """
    s = s.strip().lower().replace("_", " ")
    now = _datetime.now(_timezone.utc)
    if s == "now":
        return now
    if s == "yesterday":
        return now - _timedelta(days=1)
    m = _re.match(r"^(\d+)([hdw])\s+ago$", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        deltas = {
            "h": _timedelta(hours=n),
            "d": _timedelta(days=n),
            "w": _timedelta(weeks=n),
        }
        return now - deltas[unit]
    return _datetime.fromisoformat(s)


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

        output_json(
            {
                "project": name,
                "entries": rows,
                "memory_dir": str(memory_dir(project_path)),
            }
        )
        return

    if not rows:
        click.echo(f"No memory entries for project {name}.")
        click.echo(f"  (memory dir: {memory_dir(project_path)})")
        return

    click.echo(f"Memory entries for {name}:")
    for r in rows:
        click.echo(f"  [{r['type']}] {r['filename']} — {r['description']}")


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

    raise click.ClickException(f"No memory entry matching {topic!r} in {d}.")


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
def memory_delete(project: str | None, filename: str, force: bool) -> None:
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


@memory.command("curate")
@click.argument("project", required=False, default=None)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Commit curator decisions to disk (default is dry-run).",
)
def memory_curate(project: str | None, apply_changes: bool) -> None:
    """Run the memory curator (dry-run by default).

    With no flags: prints proposed merge/archive/flag decisions without
    touching the memory directory. Run with --apply to commit them.

    The curator invokes the ``memory_curator`` agent role with a
    snapshot of the project's memory directory and parses its proposed
    decisions out of the response. Decisions are listed one-per-line
    with their action + reason so the user can eyeball them before
    re-running with --apply.
    """
    import asyncio
    import threading

    from urika.agents.runner import get_runner
    from urika.core import memory_curator as _curator_mod

    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    runner = get_runner()

    # The CLI is also dispatched from the REPL/TUI ``/memory curate``
    # slash command (via ``click.Context.invoke``) which runs inside an
    # already-running asyncio loop. ``asyncio.run`` would then raise
    # ``RuntimeError: asyncio.run() cannot be called from a running
    # event loop``. Detect that case and run the coroutine on a fresh
    # loop in a worker thread instead — same as the telegram channel.
    # Late module-level lookup of ``run_curator`` keeps monkeypatches in
    # tests (which patch ``urika.core.memory_curator.run_curator``)
    # working transparently.
    def _call() -> "object":
        return _curator_mod.run_curator(
            project_path, runner=runner, apply=apply_changes
        )

    try:
        asyncio.get_running_loop()
        running_loop = True
    except RuntimeError:
        running_loop = False

    if not running_loop:
        result = asyncio.run(_call())
    else:
        # A loop is already spinning in this thread (REPL/TUI). Run the
        # coroutine on its own loop in a worker thread and wait.
        box: list[object] = [None]

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                box[0] = loop.run_until_complete(_call())
            except BaseException as exc:  # noqa: BLE001
                box[0] = exc
            finally:
                loop.close()

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join()
        if isinstance(box[0], BaseException):
            raise box[0]
        result = box[0]  # type: ignore[assignment]

    if result.error:
        click.secho(f"Memory curator failed: {result.error}", fg="red", err=True)
        raise SystemExit(1)

    if not result.decisions:
        click.echo("Memory curator: no changes suggested.")
        return

    suffix = "applied" if result.applied else "dry-run"
    click.echo(f"Memory curator: {len(result.decisions)} decision(s) ({suffix})")
    for d in result.decisions:
        action = d.get("action", "?")
        reason = (d.get("reason") or "").strip()
        target = d.get("filename") or d.get("into") or ""
        if target:
            click.echo(f"  - {action} {target}: {reason}")
        else:
            click.echo(f"  - {action}: {reason}")
    if not result.applied:
        click.echo("\nRe-run with --apply to commit these changes.")


@memory.command("archive")
@click.argument("project", required=False, default=None)
@click.option(
    "--month",
    default=None,
    help="Filter to one YYYY-MM month (e.g. 2024-01).",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit machine-readable JSON.",
)
def memory_archive(project: str | None, month: str | None, json_output: bool) -> None:
    """List archived memory entries.

    Archived entries live under ``<project>/memory/archive/<YYYY-MM>/``
    and are produced by the curator (``urika memory curate --apply``).
    With no flags, prints one line per entry grouped by month. Pass
    ``--month YYYY-MM`` to scope the listing to a single month.
    """
    import json as _json

    from urika.core.project_memory import list_archive

    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    entries = list_archive(project_path, month=month)

    if json_output:
        click.echo(_json.dumps(entries, indent=2))
        return

    if not entries:
        click.echo("No archived entries.")
        return

    for e in entries:
        click.echo(
            f"  [{e['month']}] {e['type']:8s} {e['filename']:36s} {e['description']}"
        )


@memory.command("diff")
@click.argument("project", required=False, default=None)
@click.argument("from_ts")
@click.argument("to_ts")
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit machine-readable JSON.",
)
def memory_diff(
    project: str | None,
    from_ts: str,
    to_ts: str,
    json_output: bool,
) -> None:
    """Show memory entries added / archived / trashed between two timestamps.

    Timestamps can be ISO 8601 (e.g. ``2024-01-15T10:00:00+00:00``) or
    one of the relative forms: ``now``, ``yesterday``, ``1h ago``,
    ``2d ago``, ``1w ago``. Underscores work in place of spaces
    (``1h_ago``) so the REPL slash command can use single-token args.
    """
    import json as _json

    from urika.core.project_memory import diff_between

    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    try:
        f = _parse_relative(from_ts)
        t = _parse_relative(to_ts)
    except (ValueError, KeyError) as exc:
        click.secho(f"Cannot parse timestamp: {exc}", fg="red", err=True)
        raise SystemExit(1)

    diff = diff_between(project_path, f, t)

    if json_output:
        click.echo(_json.dumps(diff, indent=2))
        return

    any_output = False
    for label, group in (
        ("added", diff["added"]),
        ("archived", diff["archived"]),
        ("trashed", diff["trashed"]),
    ):
        if group:
            any_output = True
            click.echo(f"\n  {label}:")
            for e in group:
                month_str = f" [{e.get('month', '')}]" if e.get("month") else ""
                click.echo(f"    {e['filename']}{month_str}")
    if not any_output:
        click.echo("No changes in the given window.")
