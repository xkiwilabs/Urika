"""`urika finalize` command.

Split out of cli/agents.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``finalize``.
"""

from __future__ import annotations

import asyncio

import click

from urika.cli._base import cli
from urika.cli._helpers import (
    _agent_run_start,
    _ensure_project,
    _resolve_project,
)
from urika.core.errors import ConfigError


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
def finalize(
    project: str | None,
    instructions: str,
    json_output: bool,
    audience: str | None = None,
    draft: bool = False,
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
        from urika.agents.runner import get_runner
        from urika.orchestrator.finalize import finalize_project
    except ImportError:
        raise ConfigError(
            "Claude Agent SDK not installed.",
            hint="Run: pip install claude-agent-sdk",
        )

    runner = get_runner()
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

        output_json(result)
        return

    if result.get("success"):
        if draft:
            draft_dir = project_path / "projectbook" / "draft"
            print_success("Draft summary saved to projectbook/draft/")
            click.echo(f"  Findings:      {draft_dir / 'findings.json'}")
            click.echo(f"  Report:        {draft_dir / 'report.md'}")
            click.echo(
                f"  Presentation:  {draft_dir / 'presentation' / 'index.html'}"
            )
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
    else:
        print_error(f"Finalization failed: {result.get('error', 'unknown')}")
