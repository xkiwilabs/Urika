"""Interactive REPL shell for Urika.

Provides a prompt_toolkit-based shell with tab completion,
command history, and a status toolbar. Agent commands run in
a background thread while the prompt stays active for input
queuing (Phase B async input via patch_stdout).
"""

from __future__ import annotations

import asyncio
import json
import os
import threading

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

from urika.cli_display import (
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

# Commands that invoke agents and should run in the background
_BLOCKING_COMMANDS = {
    "run", "finalize", "evaluate", "plan", "advisor",
    "present", "report", "build-tool", "new",
}


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
                for name in get_command_names(self.session):
                    if name.startswith(cmd):
                        yield Completion(name, start_position=-len(cmd))
            elif len(parts) >= 1:
                if cmd == "project":
                    arg = parts[1] if len(parts) > 1 else ""
                    for name in get_project_names():
                        if name.startswith(arg):
                            yield Completion(
                                name, start_position=-len(arg)
                            )
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
                            yield Completion(
                                eid, start_position=-len(arg)
                            )


def run_repl() -> None:
    """Main REPL entry point."""
    session = ReplSession()
    history = InMemoryHistory()
    completer = UrikaCompleter(session)

    from urika.repl_commands import get_global_stats

    # Show header
    print_header()

    # Show global stats
    stats = get_global_stats()
    click.echo(
        f"  {_C.DIM}{stats['projects']} projects · "
        f"{stats['experiments']} experiments · "
        f"{stats['methods']} methods · "
        f"{stats['sdk']}{_C.RESET}"
    )

    # Check for updates (uses 24h cache, 3s timeout)
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

    # ── Status line (printed before prompt, not a footer) ──
    _privacy_cache: dict[str, str] = {}

    def _get_privacy(project_path) -> str:
        key = str(project_path)
        if key not in _privacy_cache:
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(project_path)
                _privacy_cache[key] = rc.privacy_mode
            except Exception:
                _privacy_cache[key] = "open"
        return _privacy_cache[key]

    def _print_status_line():
        """Print status info right before the prompt."""
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80

        parts = []
        parts.append(f" {_C.BLUE}{_C.BOLD}urika{_C.RESET}")
        if session.has_project:
            parts.append(
                f" {_C.DIM}\u00b7 {session.project_name}"
                f"{_C.RESET}"
            )
            privacy = _get_privacy(session.project_path)
            if privacy != "open":
                parts.append(
                    f" {_C.YELLOW}\u00b7 {privacy}{_C.RESET}"
                )
        if session.model:
            parts.append(
                f" {_C.CYAN}\u00b7 {session.model}{_C.RESET}"
            )
        elapsed = _format_duration(session.elapsed_ms)
        parts.append(f" {_C.RED}\u00b7 {elapsed}{_C.RESET}")
        if session.agent_calls > 0:
            tokens = (
                session.total_tokens_in
                + session.total_tokens_out
            )
            tok_str = (
                f"{tokens / 1000:.0f}K"
                if tokens >= 1000
                else str(tokens)
            )
            parts.append(
                f" {_C.DIM}\u00b7 {tok_str} tokens"
                f" \u00b7 {session.agent_calls} calls"
                f"{_C.RESET}"
            )
            if session.total_cost_usd > 0:
                parts.append(
                    f" {_C.GREEN}\u00b7"
                    f" ~${session.total_cost_usd:.2f}"
                    f"{_C.RESET}"
                )

        sep = f"{_C.DIM}\u2500{_C.RESET}" * cols
        click.echo(sep)
        click.echo("".join(parts))

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
    )

    # ── Main loop ────────────────────────────────────────
    # patch_stdout ensures that print() output from background
    # threads appears cleanly above the prompt, without ANSI
    # conflicts. This is how Claude Code-style flowing input works.
    with patch_stdout():
        while True:
            try:
                _print_status_line()

                user_input = prompt_session.prompt(
                    "\u203a "
                ).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    _handle_command(
                        session, user_input, prompt_session
                    )
                else:
                    _handle_free_text_async(
                        session, user_input, prompt_session
                    )

            except (EOFError, KeyboardInterrupt):
                session.save_usage()
                click.echo("\n  Goodbye.")
                break
            except SystemExit:
                session.save_usage()
                break


def _handle_command(
    session: ReplSession,
    text: str,
    prompt_session: PromptSession | None = None,
) -> None:
    """Parse and execute a slash command.

    Blocking commands (agent-invoking) run in a background thread
    so the prompt stays active for input queuing.
    """
    parts = text[1:].split(" ", 1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    all_cmds = get_all_commands(session)
    if cmd_name not in all_cmds:
        if cmd_name in PROJECT_COMMANDS and not session.has_project:
            print_error(
                "Load a project first: /project <name>"
            )
        else:
            print_error(
                f"Unknown command: /{cmd_name}. "
                f"Type /help for commands."
            )
        return

    handler = all_cmds[cmd_name]["func"]

    if cmd_name in _BLOCKING_COMMANDS and prompt_session is not None:
        _run_in_background(session, handler, args, prompt_session)
    else:
        try:
            handler(session, args)
        except Exception as exc:
            print_error(f"Error: {exc}")


def _run_in_background(
    session: ReplSession,
    handler: object,
    args: str,
    prompt_session: PromptSession,
) -> None:
    """Run a command handler in a background thread.

    While the handler runs, the prompt stays active. Any input
    the user types is queued via session.queue_input() and will
    be injected into the next agent call by the orchestrator.
    """
    done = threading.Event()

    def _worker() -> None:
        try:
            handler(session, args)
        except SystemExit:
            pass
        except Exception as exc:
            print_error(f"Error: {exc}")
        finally:
            session.set_agent_idle()
            done.set()

    session.set_agent_running(agent_name="working")
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    # Keep prompting while agent runs — input goes to queue
    while not done.is_set():
        try:
            user_input = prompt_session.prompt(
                "\u203a "
            ).strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                # Allow non-blocking commands while agent runs
                parts = user_input[1:].split(" ", 1)
                cmd = parts[0].lower()
                if cmd == "quit":
                    session.save_usage()
                    raise SystemExit(0)
                if cmd not in _BLOCKING_COMMANDS:
                    _handle_command(session, user_input)
                else:
                    click.echo(
                        f"  {_C.DIM}[queued] "
                        f"{user_input}{_C.RESET}"
                    )
                    session.queue_input(user_input)
            else:
                click.echo(
                    f"  {_C.DIM}[queued] "
                    f"{user_input}{_C.RESET}"
                )
                session.queue_input(user_input)

        except (EOFError, KeyboardInterrupt):
            # Ctrl+C while agent is running — wait for it
            if not done.is_set():
                click.echo(
                    f"\n  {_C.DIM}Agent still running... "
                    f"waiting{_C.RESET}"
                )
                done.wait(timeout=2)
            break

    t.join(timeout=5)


def _handle_free_text_async(
    session: ReplSession,
    text: str,
    prompt_session: PromptSession,
) -> None:
    """Send free text to advisor, running in background."""
    if not session.has_project:
        click.echo(
            "  Load a project first: /project <name>"
        )
        return

    def _advisor_handler(_session, _args):
        _handle_free_text(_session, _args)

    _run_in_background(
        session, _advisor_handler, text, prompt_session
    )


def _handle_free_text(
    session: ReplSession, text: str
) -> None:
    """Send free text to the advisor agent."""
    if not session.has_project:
        click.echo(
            "  Load a project first: /project <name>"
        )
        return

    try:
        from urika.agents.registry import AgentRegistry
        from urika.agents.runner import get_runner
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
            "cost": session.total_cost_usd,
        }
        with Spinner("Thinking", session_info=session_info) as sp:

            def _on_msg_with_footer(msg):
                _on_msg(msg)
                model = getattr(msg, "model", None)
                if model:
                    sp.update_session(model=model)

            result = asyncio.run(
                runner.run(
                    config,
                    context,
                    on_message=_on_msg_with_footer,
                )
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
            session.add_message(
                "advisor", result.text_output.strip()
            )
        else:
            print_error(f"Advisor error: {result.error}")

    except ImportError:
        print_error(
            "Claude Agent SDK not installed."
        )
    except Exception as exc:
        print_error(f"Error: {exc}")
