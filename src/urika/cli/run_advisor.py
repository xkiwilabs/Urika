"""Advisor-suggestion offer flow used by `urika run` and `urika advisor`.

Split out of cli/run.py as part of Phase 8 refactoring. The function
parses an advisor agent's output, and if it surfaces structured
suggestions, prompts the user to run the first one immediately.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from urika.cli._helpers import _prompt_numbered


def _offer_to_run_advisor_suggestions(
    advisor_output: str, project_name: str, project_path: Path
) -> None:
    """Parse advisor suggestions and offer to run them via the CLI."""
    from urika.orchestrator.parsing import parse_suggestions

    parsed = parse_suggestions(advisor_output)
    if not parsed or not parsed.get("suggestions"):
        return

    suggestions = parsed["suggestions"]

    from urika.cli_display import _C

    click.echo(
        f"  {_C.BOLD}The advisor suggested {len(suggestions)} experiment(s):{_C.RESET}"
    )
    for i, s in enumerate(suggestions, 1):
        name = s.get("name", f"experiment-{i}")
        click.echo(f"    {i}. {name}")
    click.echo()

    # Refuse to auto-run experiments when there's no human at the
    # terminal to confirm. The dashboard spawns ``urika advisor`` as a
    # detached subprocess with ``stdin=DEVNULL``; without this guard,
    # the prompt below silently falls back to the default ("Yes —
    # start running now") on EOFError, which auto-fires a
    # multi-hour experiment from a chat message. Users in the
    # dashboard launch experiments explicitly via "New experiment"
    # in the experiment list.
    _tui_active = getattr(sys.stdin, "_tui_bridge", False)
    if not sys.stdin.isatty() and not _tui_active:
        click.echo(
            "  To run any of these, click \"New experiment\" in the dashboard's "
            "experiment list, or run `urika run "
            f"{project_name} --experiment <name>` from a terminal."
        )
        return

    try:
        choice = _prompt_numbered(
            "  Run these experiments?",
            [
                "Yes — start running now",
                "No — I'll run later with urika run",
            ],
            default=1,
        )
    except (click.Abort, click.exceptions.Abort):
        return

    if not choice.startswith("Yes"):
        return

    # Create experiment from first suggestion and run it
    suggestion = suggestions[0]
    exp_name = suggestion.get("name", "advisor-experiment").replace(" ", "-").lower()
    description = suggestion.get("method", suggestion.get("description", ""))

    from urika.core.experiment import create_experiment
    from urika.cli_display import print_success
    from urika.cli.run import run

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")

    ctx = click.Context(run)
    ctx.invoke(
        run,
        project=project_name,
        experiment_id=exp.experiment_id,
        max_turns=None,
        resume=False,
        quiet=False,
        auto=False,
        dry_run=False,
        instructions=description,
        max_experiments=None,
        review_criteria=False,
        json_output=False,
    )
