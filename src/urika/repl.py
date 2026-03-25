"""Interactive REPL shell for Urika — unified three-zone interface.

Three zones:
  Top:    Output stream (scrolls naturally via patch_stdout)
  Middle: Input line (always available, even during agent runs)
  Bottom: Status bar (prompt_toolkit bottom_toolbar)

Agent commands run in a background thread so the input loop stays
responsive.  User input typed during an agent run is queued via
``ReplSession.queue_input`` for injection into the next agent call.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from urika.cli_display import (
    _AGENT_ACTIVITY,
    _AGENT_COLORS,
    _AGENT_LABELS,
    _C,
    _format_duration,
    print_agent,
    print_error,
    print_header,
)
from urika.repl_commands import (
    PROJECT_COMMANDS,
    get_all_commands,
    get_command_names,
    get_experiment_ids,
    get_project_names,
)
from urika.repl_session import ReplSession

# Commands that trigger long-running agent work.
# These are run in a background thread so the prompt stays responsive.
_BACKGROUND_COMMANDS = {"run", "finalize"}


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
    """Main REPL entry point — unified three-zone interface."""
    session = ReplSession()
    history = InMemoryHistory()
    completer = UrikaCompleter(session)

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
            click.echo(f"  {_C.YELLOW}\u2191 {msg}{_C.RESET}")
    except Exception:
        pass

    click.echo()

    # ── Toolbar ──────────────────────────────────────────────────
    # Cached privacy mode to avoid disk reads on every keypress
    _privacy_cache: dict[str, str] = {}

    def _get_privacy(project_path) -> str:
        """Get privacy mode with caching (toolbar is called on every keypress)."""
        key = str(project_path)
        if key not in _privacy_cache:
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(project_path)
                _privacy_cache[key] = rc.privacy_mode
            except Exception:
                _privacy_cache[key] = "open"
        return _privacy_cache[key]

    def _bottom_toolbar():
        """Dynamic bottom toolbar — shows different content based on state.

        When idle:
          ─────────────────────
          urika · my-study · private · 2m 14s · 45K tokens · ~$0.23

        When agent running:
          ─────────────────────
          urika · my-study · Turn 3/5 · Task Agent · Running experiment…
          qwen3-coder · 45K tokens · ~$0.23 · 2m 14s
        """
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80

        sep = "\033[2m" + "\u2500" * cols + "\033[0m"

        if session.agent_running:
            return _toolbar_agent_running(session, sep)
        return _toolbar_idle(session, sep, _get_privacy)

    custom_style = Style.from_dict(
        {
            "bottom-toolbar": "noreverse",
        }
    )

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        bottom_toolbar=_bottom_toolbar,
        style=custom_style,
    )

    # Background thread tracking
    agent_thread: list[threading.Thread | None] = [None]

    # ── Main loop ────────────────────────────────────────────────
    with patch_stdout():
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

                # If an agent is running, queue input instead of executing
                if session.agent_running:
                    session.queue_input(user_input)
                    click.echo(
                        f"  {_C.DIM}(queued: "
                        f"{user_input[:50]}{'...' if len(user_input) > 50 else ''}"
                        f"){_C.RESET}"
                    )
                    continue

                # Check if this is a command that should run in background
                if user_input.startswith("/"):
                    parts = user_input[1:].split(" ", 1)
                    cmd_name = parts[0].lower()

                    if cmd_name in _BACKGROUND_COMMANDS:
                        _run_command_in_background(session, user_input, agent_thread)
                        continue

                # Normal synchronous handling
                if user_input.startswith("/"):
                    _handle_command(session, user_input)
                else:
                    # Free text (advisor) also runs in background
                    _run_free_text_in_background(session, user_input, agent_thread)

            except (EOFError, KeyboardInterrupt):
                if session.agent_running:
                    # Let the user know the agent is still running
                    click.echo(
                        f"\n  {_C.YELLOW}Agent still running in background. "
                        f"Press Ctrl+C again to force quit.{_C.RESET}"
                    )
                    session.set_agent_idle()
                session.save_usage()
                click.echo("\n  Goodbye.")
                break
            except SystemExit:
                session.save_usage()
                break


# ── Toolbar builders ─────────────────────────────────────────────


def _toolbar_idle(session: ReplSession, sep: str, get_privacy) -> ANSI:
    """Build the idle toolbar content."""
    parts = [sep + "\n"]
    parts.append(" \033[34;1murika\033[0m")
    if session.has_project:
        parts.append(f" \033[2m\u00b7 {session.project_name}\033[0m")
        privacy = get_privacy(session.project_path)
        if privacy != "open":
            parts.append(f" \033[33m\u00b7 {privacy}\033[0m")
    if session.model:
        parts.append(f" \033[36m\u00b7 {session.model}\033[0m")
    elapsed = _format_duration(session.elapsed_ms)
    parts.append(f" \033[31m\u00b7 {elapsed}\033[0m")
    if session.agent_calls > 0:
        tokens = session.total_tokens_in + session.total_tokens_out
        tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
        parts.append(
            f" \033[2m\u00b7 {tok_str} tokens \u00b7 {session.agent_calls} calls\033[0m"
        )
        if session.total_cost_usd > 0:
            parts.append(f" \033[32m\u00b7 ~${session.total_cost_usd:.2f}\033[0m")
    return ANSI("".join(parts))


def _toolbar_agent_running(session: ReplSession, sep: str) -> ANSI:
    """Build the toolbar for when an agent is running (two content lines)."""
    # Line 1: separator + agent info
    agent_color = _AGENT_COLORS.get(session.agent_name, "\033[34m")
    agent_label = _AGENT_LABELS.get(session.agent_name, session.agent_name)
    activity = session.agent_activity or "Working\u2026"

    line1_parts = [sep + "\n"]
    line1_parts.append(" \033[34;1murika\033[0m")
    if session.has_project:
        line1_parts.append(f" \033[2m\u00b7 {session.project_name}\033[0m")
    if session.agent_turn:
        line1_parts.append(f" \033[2m\u00b7 {session.agent_turn}\033[0m")
    line1_parts.append(f" {agent_color}\u00b7 {agent_label}\033[0m")
    line1_parts.append(f" \033[34m\u00b7 {activity}\033[0m")

    # Line 2: model, tokens, cost, elapsed
    line2_parts = []
    if session.model:
        line2_parts.append(f"\033[36m{session.model}\033[0m")
    if session.agent_calls > 0:
        tokens = session.total_tokens_in + session.total_tokens_out
        tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
        line2_parts.append(f"\033[2m{tok_str} tokens\033[0m")
    if session.total_cost_usd > 0:
        line2_parts.append(f"\033[32m~${session.total_cost_usd:.2f}\033[0m")
    elapsed = _format_duration(session.elapsed_ms)
    line2_parts.append(f"\033[31m{elapsed}\033[0m")

    line2 = " \033[2m\u00b7\033[0m ".join(line2_parts)

    return ANSI("".join(line1_parts) + "\n " + line2)


# ── Background execution ─────────────────────────────────────────


def _run_command_in_background(
    session: ReplSession,
    text: str,
    thread_ref: list[threading.Thread | None],
) -> None:
    """Run a slash command in a background thread."""
    parts = text[1:].split(" ", 1)
    cmd_name = parts[0].lower()

    all_cmds = get_all_commands(session)
    if cmd_name not in all_cmds:
        if cmd_name in PROJECT_COMMANDS and not session.has_project:
            print_error("Load a project first: /project <name>")
        else:
            print_error(f"Unknown command: /{cmd_name}. Type /help for commands.")
        return

    handler = all_cmds[cmd_name]["func"]
    args = parts[1] if len(parts) > 1 else ""

    session.set_agent_running(agent_name=cmd_name, activity="Starting\u2026")

    def _worker():
        try:
            handler(session, args)
        except Exception as exc:
            print_error(f"Error: {exc}")
            session.set_agent_idle(error=str(exc))
            return
        session.set_agent_idle()
        # Show any error that was set
        if session.agent_error:
            click.echo(f"  {_C.RED}Agent error: {session.agent_error}{_C.RESET}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread_ref[0] = thread
    thread.start()


def _run_free_text_in_background(
    session: ReplSession,
    text: str,
    thread_ref: list[threading.Thread | None],
) -> None:
    """Run the advisor agent in a background thread."""
    if not session.has_project:
        click.echo("  Load a project first: /project <name>")
        return

    session.set_agent_running(
        agent_name="advisor_agent",
        activity=_AGENT_ACTIVITY.get("advisor_agent", "Thinking\u2026"),
    )

    def _worker():
        try:
            _handle_free_text(session, text)
        except Exception as exc:
            print_error(f"Error: {exc}")
        finally:
            session.set_agent_idle()

    thread = threading.Thread(target=_worker, daemon=True)
    thread_ref[0] = thread
    thread.start()


# ── Command dispatch ─────────────────────────────────────────────


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
                    session.update_agent_activity(model=model)

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
