"""``urika sessions`` group — list / export orchestrator chat sessions.

v0.4 Track 2 cheap win. Sessions live at
``<project>/.urika/sessions/<id>.json`` and the dashboard already
renders them. This adds a CLI surface so users can:

- ``urika sessions list <project>`` — list session IDs + previews
- ``urika sessions export <project> <session-id>`` — export to
  Markdown (default) or JSON for sharing / archiving

Pre-v0.4 the only export path was reading the JSON file off disk
manually.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import _ensure_project, _resolve_project


@cli.group()
def sessions() -> None:
    """List or export persisted orchestrator chat sessions."""


@sessions.command("list")
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def sessions_list(project: str | None, json_output: bool) -> None:
    """List the project's persisted orchestrator sessions."""
    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    from urika.core.orchestrator_sessions import list_sessions

    rows = list_sessions(project_path, limit=50)

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"project": name, "sessions": rows})
        return

    if not rows:
        click.echo(f"No sessions for project {name}.")
        return

    click.echo(f"Sessions for {name}:")
    for row in rows:
        sid = row.get("session_id", "?")
        preview = (row.get("preview") or "").replace("\n", " ")[:80]
        updated = row.get("updated", "")
        click.echo(f"  {sid}  {updated}  — {preview}")


@sessions.command("export")
@click.argument("project", required=False, default=None)
@click.argument("session_id")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["md", "json"]),
    default="md",
    help="Output format. Default: md (Markdown).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write to this file. Default: stdout.",
)
def sessions_export(
    project: str | None,
    session_id: str,
    fmt: str,
    output: str | None,
) -> None:
    """Export an orchestrator session to Markdown or JSON.

    Markdown format is suitable for sharing in PRs / papers /
    project notebooks; JSON preserves every field including the
    older_summary roll-up.
    """
    name = _ensure_project(project)
    project_path, _ = _resolve_project(name)

    from urika.core.orchestrator_sessions import load_session

    session = load_session(project_path, session_id)
    if session is None:
        raise click.ClickException(
            f"Session {session_id!r} not found in project {name!r}."
        )

    if fmt == "json":
        text = json.dumps(session.to_dict(), indent=2)
    else:
        text = _render_markdown(session, project_name=name)

    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.echo(f"  Wrote {output}")
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")


def _render_markdown(session, *, project_name: str) -> str:
    """Render an OrchestratorSession as Markdown."""
    lines: list[str] = []
    lines.append(f"# Orchestrator session — {session.session_id}")
    lines.append("")
    lines.append(f"- **Project:** {project_name}")
    lines.append(f"- **Started:** {session.started}")
    lines.append(f"- **Updated:** {session.updated}")
    if session.preview:
        preview = session.preview.replace("\n", " ")
        lines.append(f"- **Preview:** {preview}")
    lines.append("")
    if session.older_summary:
        lines.append("## Earlier conversation (rolled-up summary)")
        lines.append("")
        lines.append(session.older_summary)
        lines.append("")
    if session.recent_messages:
        lines.append("## Recent messages")
        lines.append("")
        for msg in session.recent_messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            ts = msg.get("ts", "")
            lines.append(f"### {role}{f'  ·  {ts}' if ts else ''}")
            lines.append("")
            lines.append(content if isinstance(content, str) else json.dumps(content))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
