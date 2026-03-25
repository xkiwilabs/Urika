"""Interactive REPL shell for Urika."""

from __future__ import annotations

import asyncio
import json
import os

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory

from urika.cli_display import print_agent, print_error, print_header
from urika.repl_commands import (
    PROJECT_COMMANDS,
    get_all_commands,
    get_command_names,
    get_experiment_ids,
    get_project_names,
)
from urika.repl_session import ReplSession


class UrikaCompleter(Completer):
    """Tab completer for REPL — commands, project names, experiment IDs."""

    def __init__(self, session: ReplSession):
        self.session = session

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()

        if text.startswith("/"):
            parts = text[1:].split(" ", 1)
            cmd = parts[0]

            if len(parts) == 1 and not text.endswith(" "):
                # Completing the command name
                for name in get_command_names(self.session):
                    if name.startswith(cmd):
                        yield Completion(name, start_position=-len(cmd))
            elif len(parts) >= 1:
                # Completing arguments
                if cmd == "project":
                    arg = parts[1] if len(parts) > 1 else ""
                    for name in get_project_names():
                        if name.startswith(arg):
                            yield Completion(name, start_position=-len(arg))
                elif cmd in (
                    "present",
                    "logs",
                    "evaluate",
                    "report",
                    "plan",
                    "results",
                    "resume",
                ):
                    arg = parts[1] if len(parts) > 1 else ""
                    for eid in get_experiment_ids(self.session):
                        if eid.startswith(arg):
                            yield Completion(eid, start_position=-len(arg))


def run_repl() -> None:
    """Main REPL entry point."""
    session = ReplSession()
    history = InMemoryHistory()
    completer = UrikaCompleter(session)

    from urika.cli_display import _C
    from urika.repl_commands import get_global_stats

    # Show header
    print_header()

    # Show global stats footer
    stats = get_global_stats()
    click.echo(
        f"  {_C.DIM}{stats['projects']} projects · "
        f"{stats['experiments']} experiments · "
        f"{stats['methods']} methods · "
        f"{stats['sdk']}{_C.RESET}"
    )

    # Check for updates (uses 24h cache, non-blocking 3s timeout)
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates()
        if update_info:
            msg = format_update_message(update_info)
            click.echo(
                f"  {_C.YELLOW}↑ {msg}{_C.RESET}"
            )
    except Exception:
        pass

    click.echo()

    # Projects available via /list

    from prompt_toolkit.formatted_text import ANSI
    from urika.cli_display import _format_duration

    def _bottom_toolbar():
        """Dynamic bottom toolbar — grey separator, colored text, no shading."""
        parts = []
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        parts.append("\033[2m" + "─" * cols + "\033[0m\n")
        parts.append(" \033[34;1murika\033[0m")
        if session.has_project:
            parts.append(f" \033[2m· {session.project_name}\033[0m")
            # Show privacy mode if not open
            try:
                from urika.agents.config import load_runtime_config
                rc = load_runtime_config(session.project_path)
                if rc.privacy_mode != "open":
                    parts.append(f" \033[33m· {rc.privacy_mode}\033[0m")
            except Exception:
                pass
        if session.model:
            parts.append(f" \033[36m· {session.model}\033[0m")
        elapsed = _format_duration(session.elapsed_ms)
        parts.append(f" \033[31m· {elapsed}\033[0m")
        if session.agent_calls > 0:
            tokens = session.total_tokens_in + session.total_tokens_out
            tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
            parts.append(
                f" \033[2m· {tok_str} tokens · {session.agent_calls} calls\033[0m"
            )
            if session.total_cost_usd > 0:
                parts.append(f" \033[32m· ~${session.total_cost_usd:.2f}\033[0m")
        return ANSI("".join(parts))

    from prompt_toolkit.styles import Style

    custom_style = Style.from_dict({
        'bottom-toolbar': 'noreverse',
    })

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        bottom_toolbar=_bottom_toolbar,
        style=custom_style,
    )

    while True:
        try:
            # Build prompt
            if session.has_project:
                prompt_text = f"urika:{session.project_name}> "
            else:
                prompt_text = "urika> "

            user_input = prompt_session.prompt(prompt_text).strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                _handle_command(session, user_input)
            else:
                _handle_free_text(session, user_input)

        except (EOFError, KeyboardInterrupt):
            session.save_usage()
            click.echo("\n  Goodbye.")
            break
        except SystemExit:
            session.save_usage()
            break


def _handle_command(session: ReplSession, text: str) -> None:
    """Parse and execute a slash command."""
    parts = text[1:].split(" ", 1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    all_cmds = get_all_commands(session)
    if cmd_name not in all_cmds:
        # Check if it's a project command but no project loaded
        if cmd_name in PROJECT_COMMANDS and not session.has_project:
            print_error("Load a project first: /project <name>")
        else:
            print_error(f"Unknown command: /{cmd_name}. Type /help for commands.")
        return

    handler = all_cmds[cmd_name]["func"]
    try:
        handler(session, args)
    except Exception as exc:
        print_error(f"Error: {exc}")


def _handle_free_text(session: ReplSession, text: str) -> None:
    """Send free text to the advisor agent."""
    if not session.has_project:
        click.echo("  Load a project first: /project <name>")
        return

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
        from urika.cli import _make_on_message
        from urika.cli_display import Spinner

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()

        advisor = registry.get("advisor_agent")
        if advisor is None:
            print_error("Advisor agent not found.")
            return

        # Build context
        context = f"Project: {session.project_name}\n"
        conv = session.get_conversation_context()
        if conv:
            context += f"\nPrevious conversation:\n{conv}\n"
        context += f"\nUser: {text}\n"

        # Load project state
        methods_path = session.project_path / "methods.json"
        if methods_path.exists():
            try:
                mdata = json.loads(methods_path.read_text())
                mlist = mdata.get("methods", [])
                context += f"\n{len(mlist)} methods tried.\n"
            except Exception:
                pass

        config = advisor.build_config(
            project_dir=session.project_path, experiment_id=""
        )

        _on_msg = _make_on_message()

        print_agent("advisor_agent")
        session_info = {
            "project": session.project_name or "",
            "model": session.model or "",
            "tokens": session.total_tokens_in + session.total_tokens_out,
            "cost": session.total_cost_usd,
        }
        with Spinner("Thinking", session_info=session_info) as sp:

            def _on_msg_with_footer(msg):
                _on_msg(msg)
                # Update footer with model from message
                model = getattr(msg, "model", None)
                if model:
                    sp.update_session(model=model)

            result = asyncio.run(
                runner.run(config, context, on_message=_on_msg_with_footer)
            )

        # Track usage
        session.record_agent_call(
            tokens_in=getattr(result, "tokens_in", 0) or 0,
            tokens_out=getattr(result, "tokens_out", 0) or 0,
            cost_usd=result.cost_usd or 0.0,
            model=getattr(result, "model", "") or "",
        )

        if result.success and result.text_output:
            click.echo(f"\n{result.text_output.strip()}\n")
            session.add_message("user", text)
            session.add_message("advisor", result.text_output.strip())
        else:
            print_error(f"Advisor error: {result.error}")

    except ImportError:
        print_error("Claude Agent SDK not installed. Run: pip install urika[agents]")
    except Exception as exc:
        print_error(f"Error: {exc}")
