"""`urika finalize` command.

Split out of cli/agents.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``finalize``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import (
    _agent_run_start,
    _ensure_project,
    _export_written_artifact,
    _resolve_project,
)
from urika.core.errors import ConfigError


def _maybe_export_report(
    project_path: Path, output_format: str, draft: bool, json_output: bool
) -> Path | None:
    """v0.9.0 ``--format``: post-process the markdown report the
    finalize sequence wrote (``projectbook/final-report.md``, or
    ``projectbook/draft/report.md`` under ``--draft``).

    Returns the exported path, or None when the format is markdown or
    no report was written (the report agent's output is only persisted
    when it looks like a real report). On ExportError the underlying
    helper raises ``click.ClickException`` — non-zero exit, markdown
    artifact kept, and the message says so.
    """
    if output_format == "markdown":
        return None
    report_md = (
        project_path
        / "projectbook"
        / ("draft/report.md" if draft else "final-report.md")
    )
    if not report_md.exists():
        if not json_output:
            click.echo(f"  Nothing to export — {report_md.name} was not written.")
        return None
    return _export_written_artifact(report_md, output_format)


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Optional instructions for the finalizer agent.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--audience",
    type=click.Choice(["novice", "standard", "expert"]),
    default=None,
    help="Output audience level (default: standard).",
)
@click.option(
    "--draft",
    is_flag=True,
    default=False,
    help="Interim summary — outputs to projectbook/draft/, doesn't overwrite final outputs.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "latex", "pdf"]),
    default="markdown",
    help="Report format — latex/pdf post-process the written markdown "
    "(requires urika[export] + pandoc; pdf also needs a TeX engine).",
)
def finalize(
    project: str | None,
    instructions: str,
    json_output: bool,
    audience: str | None = None,
    draft: bool = False,
    output_format: str = "markdown",
) -> None:
    """Finalize the project — produce polished methods, report, and presentation."""
    import time

    from datetime import datetime, timezone

    from urika.cli_display import (
        ThinkingPanel,
        print_agent,
        print_error,
        print_success,
        print_tool_use,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # Resolve audience from project config if not explicitly provided
    if audience is None:
        audience = _config.audience

    from urika.agents.config import load_runtime_config

    _rc = load_runtime_config(project_path)

    try:
        from urika.agents.runner_routing import runner_for_project
        from urika.orchestrator.finalize import finalize_project
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    # Orchestrator-level entry point: ``finalize_project`` drives the
    # finalizer → report_agent → presentation_agent sequence under a
    # single runner. Route via the project default; per-agent routing
    # inside the finalize sequence is a larger refactor (orchestrator
    # would need to accept a runner-per-agent map).
    runner = runner_for_project(project_path)
    _start_ms, _start_iso = _agent_run_start()

    if json_output:

        def _on_progress(event: str, detail: str = "") -> None:
            from urika.cli.run import _update_repl_activity

            _update_repl_activity(event, detail)

        def _on_message(msg: object) -> None:
            pass

        try:
            result = asyncio.run(
                finalize_project(
                    project_path,
                    runner,
                    _on_progress,
                    _on_message,
                    instructions=instructions,
                    audience=audience,
                    draft=draft,
                )
            )
        except KeyboardInterrupt:
            click.echo("\n  Finalize stopped.")
            if instructions:
                click.echo("  Re-run with: urika finalize --instructions '...'")
            return
    else:
        panel = ThinkingPanel()
        panel.project = f"{project} · {_rc.privacy_mode}"
        panel._project_dir = project_path
        panel.activity = "Draft summary..." if draft else "Finalizing..."
        panel.activate()
        panel.start_spinner()

        def _on_progress(event: str, detail: str = "") -> None:
            from urika.cli.run import _update_repl_activity

            _update_repl_activity(event, detail)
            if event == "agent":
                agent_key = detail.split("—")[0].strip().lower().replace(" ", "_")
                print_agent(agent_key)
                panel.update(agent=agent_key, activity=detail)
            elif event == "result":
                print_success(detail)

        def _on_message(msg: object) -> None:
            try:
                model = getattr(msg, "model", None)
                if model:
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
                            panel.set_thinking(tool_name)
                        else:
                            panel.set_thinking("Thinking…")
            except Exception:
                pass

        try:
            result = asyncio.run(
                finalize_project(
                    project_path,
                    runner,
                    _on_progress,
                    _on_message,
                    instructions=instructions,
                    audience=audience,
                    draft=draft,
                )
            )
        except KeyboardInterrupt:
            panel.cleanup()
            click.echo("\n  Finalize stopped.")
            click.echo("  Re-run with: urika finalize [--instructions '...']")
            return
        finally:
            panel.cleanup()

    # Record finalize usage
    try:
        from urika.core.usage import record_session

        _elapsed_ms = int(time.monotonic() * 1000) - _start_ms
        record_session(
            project_path,
            started=_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=_elapsed_ms,
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            cost_usd=result.get("cost_usd", 0.0),
            agent_calls=result.get("agent_calls", 0),
            experiments_run=0,
        )
    except Exception:
        pass

    if json_output:
        from urika.cli_helpers import output_json

        if result.get("success"):
            export_path = _maybe_export_report(
                project_path, output_format, draft, json_output=True
            )
            if export_path is not None:
                result["export_path"] = str(export_path)
        output_json(result)
        return

    if result.get("success"):
        if draft:
            draft_dir = project_path / "projectbook" / "draft"
            print_success("Draft summary saved to projectbook/draft/")
            click.echo(f"  Findings:      {draft_dir / 'findings.json'}")
            click.echo(f"  Report:        {draft_dir / 'report.md'}")
            click.echo(f"  Presentation:  {draft_dir / 'presentation' / 'index.html'}")
        else:
            print_success("Project finalized!")
            click.echo(f"  Methods:       {project_path / 'methods/'}")
            click.echo(
                f"  Final report:  {project_path / 'projectbook' / 'final-report.md'}"
            )
            click.echo(
                f"  Presentation:  "
                f"{project_path / 'projectbook' / 'final-presentation' / 'index.html'}"
            )
            click.echo(f"  Reproduce:     {project_path / 'reproduce.sh'}")

        # Auto-push to GitHub iff configured. Skipped on draft so the
        # user can iterate on draft outputs without spamming commits.
        if not draft:
            from urika.cli.github import _maybe_auto_push

            _maybe_auto_push(project_path, event="finalize")

        # v0.9.0 --format: export AFTER the auto-push so the markdown
        # backup still lands even when the export environment is
        # broken (the ClickException below exits non-zero either way).
        export_path = _maybe_export_report(
            project_path, output_format, draft, json_output=False
        )
        if export_path is not None:
            click.echo(f"  Exported:      {export_path}")
    else:
        print_error(f"Finalization failed: {result.get('error', 'unknown')}")
