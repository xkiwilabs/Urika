"""The /run slash command (REPL) — split out of repl/commands.py.

The /run flow is the heaviest single command in the REPL: it
inspects locks, prompts for run settings, optionally creates an
experiment from a pending advisor suggestion, then invokes the CLI
``run`` command. Lives in its own file because it's ~300 lines.
"""

from __future__ import annotations

import click

from urika.repl.commands_registry import command
from urika.repl.helpers import _load_run_defaults, _prompt_numbered
from urika.repl.session import ReplSession


@command("run", requires_project=True, description="Run next experiment")
def cmd_run(session: ReplSession, args: str) -> None:
    import click as _click
    from urika.cli_display import print_warning
    from urika.core.experiment import list_experiments

    is_remote = session._is_remote_command

    # Parse remote args: /run, /run 3, /run --multi 5, /run --resume, /run try trees
    remote_parsed = _parse_remote_run_args(args) if is_remote else None

    # Handle --resume via remote
    if remote_parsed and remote_parsed.get("resume"):
        from urika.repl.commands import cmd_resume

        cmd_resume(session, "")
        return

    # Check if any experiment is already running (lockfile exists)
    experiments = list_experiments(session.project_path)
    for exp in experiments:
        lock = session.project_path / "experiments" / exp.experiment_id / ".lock"
        if lock.exists():
            # Check if the owning process is still alive
            import os as _os

            try:
                pid_str = lock.read_text().strip()
                if pid_str:
                    _os.kill(int(pid_str), 0)
                    # Process alive — lock is valid
                else:
                    # Empty lock (legacy) — treat as valid conservatively
                    pass
            except (ValueError, ProcessLookupError):
                # PID dead or invalid — stale lock, clean it up
                click.echo(f"  Cleaned stale lock on {exp.experiment_id}")
                lock.unlink(missing_ok=True)
                continue
            except PermissionError:
                pass  # Process exists, can't signal — treat as valid

            if is_remote:
                click.echo(
                    f"  Experiment '{exp.experiment_id}' locked — stopping stale lock."
                )
                try:
                    from urika.core.session import stop_session

                    stop_session(
                        session.project_path,
                        exp.experiment_id,
                        reason="Stopped by remote run",
                    )
                except Exception:
                    lock.unlink(missing_ok=True)
                break

            print_warning(f"Experiment '{exp.experiment_id}' is currently running.")
            choice = _prompt_numbered(
                "  What would you like to do?",
                [
                    "Wait for it to complete (recommended)",
                    "Stop it and start a new run",
                    "Cancel",
                ],
                default=1,
            )
            if choice.startswith("Wait"):
                click.echo("  Waiting is recommended. Check back after it completes.")
                return
            if choice.startswith("Cancel"):
                return
            # Stop it
            try:
                from urika.core.session import stop_session

                stop_session(
                    session.project_path,
                    exp.experiment_id,
                    reason="Stopped by user from REPL",
                )
                click.echo(f"  Stopped {exp.experiment_id}")
            except Exception:
                lock.unlink(missing_ok=True)
            break

    defaults = _load_run_defaults(session)

    if is_remote:
        # Remote: skip all interactive prompts, use defaults + parsed args
        max_turns = remote_parsed.get("max_turns") or defaults["max_turns"]
        auto_mode = defaults["auto_mode"]
        max_experiments = remote_parsed.get("max_experiments")
        run_instructions = remote_parsed.get("instructions", "")
        review_criteria = False
        # v0.4.2 Package I: honor --no-advisor-first / --advisor-first
        # in remote args. None means "use default" which is True.
        af_override = remote_parsed.get("advisor_first")
        advisor_first = True if af_override is None else af_override

        # Show summary
        click.echo("\n  Run settings (remote):")
        click.echo(f"    Max turns:    {max_turns}")
        if max_experiments:
            click.echo(f"    Experiments:  up to {max_experiments}")
        if run_instructions:
            instr_preview = (
                run_instructions[:80] + "..."
                if len(run_instructions) > 80
                else run_instructions
            )
            click.echo(f"    Instructions: {instr_preview}")
        click.echo()
    else:
        # Interactive: show defaults, offer custom
        click.echo("\n  Run settings:")
        click.echo(f"    Max turns: {defaults['max_turns']}")
        click.echo(f"    Auto mode: {defaults['auto_mode']}")
        instructions = (
            session.get_conversation_context() if session.conversation else "(none)"
        )
        click.echo(
            f"    Instructions: {instructions[:80]}{'...' if len(instructions) > 80 else ''}"
        )

        choice = _prompt_numbered(
            "\n  Proceed?",
            ["Run with defaults", "Custom settings", "Skip"],
            default=1,
        )

        if choice == "Skip":
            return

        max_turns = defaults["max_turns"]
        auto_mode = defaults["auto_mode"]
        max_experiments = None
        run_instructions = ""
        review_criteria = False
        advisor_first = True  # default — overridable in Custom settings

        if choice == "Custom settings":
            try:
                max_turns = int(
                    _click.prompt("  Max turns", default=str(defaults["max_turns"]))
                )
            except ValueError:
                pass  # keep default max_turns
            auto_mode = _prompt_numbered(
                "\n  Auto mode:",
                [
                    "Checkpoint — pause between experiments for review",
                    "Capped — run up to max experiments with no pauses",
                    "Unlimited — run until criteria met or advisor says done",
                ],
                default={"checkpoint": 1, "capped": 2, "unlimited": 3}.get(
                    defaults["auto_mode"], 1
                ),
            )
            # Map back to short name
            auto_mode = {
                "Checkpoint": "checkpoint",
                "Capped": "capped",
                "Unlimited": "unlimited",
            }.get(auto_mode.split("—")[0].strip(), "checkpoint")
            if auto_mode == "capped":
                try:
                    max_experiments = int(
                        _click.prompt("  Max experiments", default="10")
                    )
                except ValueError:
                    max_experiments = 10
            elif auto_mode == "unlimited":
                max_experiments = 50  # safety cap
            run_instructions = _click.prompt(
                "  Instructions (optional, enter to skip)", default=""
            )
            rc_choice = _prompt_numbered(
                "\n  Re-evaluate criteria if met?",
                [
                    "No — complete when criteria met (default)",
                    "Yes — advisor reviews criteria, may raise the bar",
                ],
                default=1,
            )
            review_criteria = rc_choice.startswith("Yes")

            af_choice = _prompt_numbered(
                "\n  Ask advisor first to suggest a name and direction?",
                [
                    "Yes — advisor proposes name/hypothesis before planner (default)",
                    "No — planner picks the first method directly",
                ],
                default=1,
            )
            advisor_first = af_choice.startswith("Yes")

        # Show settings summary
        click.echo()
        click.echo("  Run settings:")
        click.echo(f"    Max turns:    {max_turns}")
        if max_experiments:
            click.echo(f"    Experiments:  up to {max_experiments}")
            click.echo(f"    Auto mode:    {auto_mode}")
        else:
            click.echo("    Auto mode:    single experiment")
        if run_instructions:
            instr_preview = (
                run_instructions[:80] + "..."
                if len(run_instructions) > 80
                else run_instructions
            )
            click.echo(f"    Instructions: {instr_preview}")
        if review_criteria:
            click.echo("    Review criteria: yes")
        click.echo()

    # Use conversation context as instructions if none provided
    if not run_instructions and session.conversation:
        run_instructions = session.get_conversation_context()

    # If we have pending suggestions from advisor, create the experiment
    # directly instead of having cli_run call the advisor again from scratch
    use_experiment_id = None
    if session.pending_suggestions:
        suggestion = session.pending_suggestions[0]
        exp_name = (
            suggestion.get("name", "advisor-experiment").replace(" ", "-").lower()
        )
        description = suggestion.get("method", suggestion.get("description", ""))
        if run_instructions and description:
            description = f"{run_instructions}\n\n{description}"
        elif run_instructions:
            description = run_instructions

        try:
            from urika.core.experiment import create_experiment

            exp = create_experiment(
                session.project_path,
                name=exp_name,
                hypothesis=description[:500] if description else "",
            )
            use_experiment_id = exp.experiment_id
            click.echo(
                f"  Created experiment from advisor suggestion: {use_experiment_id}"
            )
            # Use description as instructions for the experiment run
            if description:
                run_instructions = description
            # Pop the used suggestion, keep the rest for subsequent runs
            session.pending_suggestions = session.pending_suggestions[1:]
        except Exception as exc:
            click.echo(f"  Could not create experiment: {exc}")
            # Fall through to normal flow

    # Run directly without going through CLI (avoids duplicate header)
    import os

    from urika.repl import commands as _cmds_mod

    def _get_user_input() -> str:
        return session.pop_queued_input()

    os.environ["URIKA_REPL"] = "1"
    _cmds_mod._user_input_callback = _get_user_input
    _cmds_mod._repl_session_ref = session
    session.set_agent_active("run")
    try:
        from urika.cli import run as cli_run

        ctx = click.Context(cli_run)
        ctx.invoke(
            cli_run,
            project=session.project_name,
            experiment_id=use_experiment_id,
            max_turns=max_turns,
            resume=False,
            quiet=False,
            auto=(is_remote or auto_mode != "checkpoint"),
            instructions=run_instructions,
            max_experiments=max_experiments,
            review_criteria=review_criteria,
            advisor_first=advisor_first,
        )
        session.experiments_run += 1
    finally:
        session.set_agent_idle()
        _cmds_mod._user_input_callback = None
        _cmds_mod._repl_session_ref = None
        os.environ.pop("URIKA_REPL", None)


def _parse_remote_run_args(args: str) -> dict:
    """Parse remote /run arguments into a settings dict.

    Supported formats:
      /run                         -> defaults
      /run 3                       -> max_turns=3
      /run --multi 5               -> max_experiments=5
      /run --resume                -> resume=True
      /run --no-advisor-first      -> advisor_first=False
      /run try trees               -> instructions="try trees"
      /run --multi 3 focus on features -> max_experiments=3, instructions="focus on features"

    v0.4.2 Package I: ``--no-advisor-first`` and the matching positive
    ``--advisor-first`` are accepted so remote callers can override the
    flag (pre-fix it was hardcoded ``True`` in the worker, leaving
    Slack/Telegram users unable to skip advisor-first even when their
    prior chat already established a direction).
    """
    result: dict = {
        "max_turns": None,
        "max_experiments": None,
        "resume": False,
        "instructions": "",
        "advisor_first": None,  # None = use default (True)
    }

    args_stripped = args.strip()
    if not args_stripped:
        return result

    parts = args_stripped.split()
    # Strip advisor-first overrides wherever they appear so positional
    # parsing below doesn't get confused by them.
    pruned: list[str] = []
    for p in parts:
        if p == "--no-advisor-first":
            result["advisor_first"] = False
        elif p == "--advisor-first":
            result["advisor_first"] = True
        else:
            pruned.append(p)
    parts = pruned
    if not parts:
        return result

    if parts[0] == "--resume":
        result["resume"] = True
    elif parts[0] == "--multi" and len(parts) > 1:
        try:
            result["max_experiments"] = int(parts[1])
            if len(parts) > 2:
                result["instructions"] = " ".join(parts[2:])
        except ValueError:
            result["instructions"] = " ".join(parts)
    else:
        try:
            result["max_turns"] = int(parts[0])
            if len(parts) > 1:
                result["instructions"] = " ".join(parts[1:])
        except ValueError:
            result["instructions"] = " ".join(parts)

    return result
