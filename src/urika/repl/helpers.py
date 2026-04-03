"""Shared helper functions for REPL commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click

from urika.cli_display import _C
from urika.repl.session import ReplSession


def _pick_experiment(
    session: ReplSession, args: str, allow_all: bool = False
) -> str | None:
    """Prompt user to pick an experiment. Returns exp_id, 'all', 'project', or None."""
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress

    exp_id = args.strip()
    if exp_id:
        return exp_id

    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No experiments.")
        return None

    # Remote: auto-pick the most recent experiment (no interactive prompt)
    if session._is_remote_command:
        exp_id = experiments[-1].experiment_id
        click.echo(f"  Auto-selected: {exp_id}")
        return exp_id

    # Build options — most recent first
    reversed_exps = list(reversed(experiments))
    options = []
    for exp in reversed_exps:
        progress = load_progress(session.project_path, exp.experiment_id)
        status = progress.get("status", "pending")
        runs = len(progress.get("runs", []))
        options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
    if allow_all:
        options.append("All experiments (generate for each)")
        options.append("Project level (one overarching report)")

    choice = _prompt_numbered("\n  Select:", options, default=1)

    if choice.startswith("All"):
        return "all"
    if choice.startswith("Project"):
        return "project"

    # Extract exp_id from the choice string
    return choice.split(" [")[0]


def _run_single_agent(
    session: ReplSession,
    agent_name: str,
    experiment_id: str,
    prompt: str,
    audience: str = "expert",
) -> str:
    """Run a single agent and display its output. Returns the text output."""
    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
        from urika.cli import _make_on_message
        from urika.cli_display import (
            Spinner,
            format_agent_output,
            print_agent,
            print_error,
        )

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()

        role = registry.get(agent_name)
        if role is None:
            print_error(f"Agent '{agent_name}' not found.")
            return ""

        print_agent(agent_name)

        _on_msg = _make_on_message()

        config = role.build_config(
            project_dir=session.project_path,
            experiment_id=experiment_id,
            audience=audience,
        )

        session_info = {
            "project": session.project_name or "",
            "model": session.model or "",
            "tokens": session.total_tokens_in + session.total_tokens_out,
            "cost": session.total_cost_usd,
        }
        with Spinner("Working", session_info=session_info) as sp:

            def _on_msg_with_footer(msg: object) -> None:
                _on_msg(msg)
                model = getattr(msg, "model", None)
                if model:
                    sp.update_session(model=model)

            result = asyncio.run(
                runner.run(config, prompt, on_message=_on_msg_with_footer)
            )

        # Track usage
        session.record_agent_call(
            tokens_in=getattr(result, "tokens_in", 0) or 0,
            tokens_out=getattr(result, "tokens_out", 0) or 0,
            cost_usd=result.cost_usd or 0.0,
            model=getattr(result, "model", "") or "",
        )

        if result.success and result.text_output:
            click.echo(format_agent_output(result.text_output))
            return result.text_output.strip()
        else:
            print_error(f"Error: {result.error}")
            return ""

    except ImportError:
        from urika.cli_display import print_error

        print_error("Claude Agent SDK not installed. Run: pip install claude-agent-sdk")
        return ""
    except Exception as exc:
        from urika.cli_display import print_error

        print_error(f"Error: {exc}")
        return ""


def _save_presentation(session: ReplSession, text: str, exp_id: str | None) -> None:
    """Parse slide JSON and render presentation, with clickable output link."""
    import tomllib

    from urika.core.presentation import parse_slide_json, render_presentation

    slide_data = parse_slide_json(text)
    if not slide_data:
        click.echo("  \u2717 Could not parse slide data from agent output")
        return

    theme = "light"
    toml_path = session.project_path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tdata = tomllib.load(f)
            theme = tdata.get("preferences", {}).get("presentation_theme", "light")
        except Exception:
            pass

    if exp_id:
        exp_dir = session.project_path / "experiments" / exp_id
        output_dir = exp_dir / "presentation"
        render_presentation(slide_data, output_dir, theme=theme, experiment_dir=exp_dir)
        display = f"experiments/{exp_id}/presentation/index.html"
    else:
        output_dir = session.project_path / "projectbook" / "presentation"
        render_presentation(slide_data, output_dir, theme=theme)
        display = "projectbook/presentation/index.html"

    pres_path = output_dir / "index.html"
    link = _file_link(pres_path, display)
    click.echo(f"  \u2713 Saved: {link}")


def _get_audience(session: ReplSession) -> str:
    """Read the audience preference from the project config."""
    import tomllib

    if session.project_path is None:
        return "expert"
    toml_path = session.project_path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            return data.get("preferences", {}).get("audience", "expert")
        except Exception:
            pass
    return "expert"


def _file_link(path: Path, display: str = "") -> str:
    """Create a clickable terminal hyperlink using OSC 8 escape sequence."""
    import sys

    label = display or str(path)
    if not sys.stdout.isatty():
        return label
    uri = path.resolve().as_uri()
    return f"\033]8;;{uri}\033\\{label}\033]8;;\033\\"


def get_global_stats() -> dict:
    """Get global Urika stats for the footer."""
    from urika.core.registry import ProjectRegistry

    stats = {"projects": 0, "experiments": 0, "methods": 0, "sdk": "unknown"}

    registry = ProjectRegistry()
    projects = registry.list_all()
    stats["projects"] = len(projects)

    for name, path in projects.items():
        try:
            from urika.core.experiment import list_experiments

            exps = list_experiments(path)
            stats["experiments"] += len(exps)
        except Exception:
            pass
        try:
            methods_path = path / "methods.json"
            if methods_path.exists():
                mdata = json.loads(methods_path.read_text(encoding="utf-8"))
                stats["methods"] += len(mdata.get("methods", []))
        except Exception:
            pass

    try:
        import claude_agent_sdk

        stats["sdk"] = f"claude-agent-sdk {claude_agent_sdk.__version__}"
    except (ImportError, AttributeError):
        stats["sdk"] = "not installed"

    return stats


def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt with numbered options. Includes Cancel option.

    Raises click.Abort on cancel or Ctrl+C.
    """
    display = list(options) + ["Cancel"]
    click.echo(prompt_text)
    for i, opt in enumerate(display, 1):
        marker = " (default)" if i == default else ""
        click.echo(f"    {i}. {opt}{marker}")
    while True:
        try:
            raw = click.prompt("  Choice", default=str(default)).strip()
        except (EOFError, KeyboardInterrupt):
            raise click.Abort()
        try:
            idx = int(raw)
            if idx == len(display):
                raise click.Abort()
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass


def get_all_commands(session: ReplSession) -> dict:
    """Get all available commands for current state."""
    from urika.repl.commands import GLOBAL_COMMANDS, PROJECT_COMMANDS

    cmds = dict(GLOBAL_COMMANDS)
    if session.has_project:
        cmds.update(PROJECT_COMMANDS)
    return cmds


def get_command_names(session: ReplSession) -> list[str]:
    """Get all command names for tab completion."""
    return sorted(get_all_commands(session).keys())


def get_project_names() -> list[str]:
    """Get all project names for tab completion."""
    from urika.core.registry import ProjectRegistry

    registry = ProjectRegistry()
    return sorted(registry.list_all().keys())


def get_experiment_ids(session: ReplSession) -> list[str]:
    """Get experiment IDs for tab completion."""
    if not session.has_project:
        return []
    from urika.core.experiment import list_experiments

    return [e.experiment_id for e in list_experiments(session.project_path)]


def _load_run_defaults(session: ReplSession) -> dict:
    """Load run defaults from urika.toml preferences."""
    import tomllib

    defaults = {"max_turns": 5, "auto_mode": "checkpoint"}
    toml_path = session.project_path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            prefs = data.get("preferences", {})
            defaults["max_turns"] = prefs.get("max_turns_per_experiment", 5)
            defaults["auto_mode"] = prefs.get("auto_mode", "checkpoint")
        except Exception:
            pass
    return defaults


def _fmt_tokens(n: int) -> str:
    """Format token count."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)
