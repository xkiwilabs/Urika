"""Interactive REPL shell for Urika.

Provides a prompt_toolkit-based shell with tab completion,
command history, and a status toolbar. Agent commands block
the input loop during execution (Phase B will add async input).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

from urika.cli_display import (
    _C,
    _format_duration,
    format_agent_output,
    print_agent,
    print_error,
    print_header,
)
from urika.repl_commands import (
    PROJECT_COMMANDS,
    cmd_advisor,
    cmd_build_tool,
    cmd_evaluate,
    cmd_finalize,
    cmd_plan,
    cmd_present,
    cmd_report,
    cmd_resume,
    cmd_run,
    get_all_commands,
    get_command_names,
    get_experiment_ids,
    get_project_names,
)
from urika.repl_session import ReplSession

logger = logging.getLogger(__name__)


def _strip_json_blocks(text: str) -> str:
    """Remove ```json ... ``` blocks from agent output for clean remote responses."""
    import re

    cleaned = re.sub(r"```json\s*\n.*?\n\s*```", "", text, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


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

    # ── Toolbar ──────────────────────────────────────────
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

    def _bottom_toolbar():
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80

        parts = []
        parts.append("\033[2m" + "\u2500" * cols + "\033[0m\n")
        parts.append(" \033[34;1murika\033[0m")
        if session.has_project:
            parts.append(f" \033[2m\u00b7 {session.project_name}\033[0m")
            privacy = _get_privacy(session.project_path)
            parts.append(f" \033[33m\u00b7 {privacy}\033[0m")
        if session.model:
            from urika.cli_display import format_model_source

            model_display = format_model_source(
                session.model,
                project_dir=session.project_path,
            )
            parts.append(f" \033[36m\u00b7 {model_display}\033[0m")
        elapsed = _format_duration(session.elapsed_ms)
        parts.append(f" \033[31m\u00b7 {elapsed}\033[0m")
        if session.agent_calls > 0:
            tokens = session.total_tokens_in + session.total_tokens_out
            tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
            parts.append(
                f" \033[2m\u00b7 {tok_str} tokens"
                f" \u00b7 {session.agent_calls} calls\033[0m"
            )
            if session.total_cost_usd > 0:
                parts.append(f" \033[32m\u00b7 ~${session.total_cost_usd:.2f}\033[0m")
        return ANSI("".join(parts))

    custom_style = Style.from_dict({"bottom-toolbar": "noreverse"})

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        bottom_toolbar=_bottom_toolbar,
        style=custom_style,
    )

    def _drain_remote_queue(session: ReplSession) -> None:
        """Execute any queued remote commands from Telegram/Slack."""
        while session.has_remote_command:
            item = session.pop_remote_command()
            if item is None:
                break
            cmd, args, respond = item
            cmd_text = f"/{cmd} {args}".strip()
            click.echo(f"\n  {_C.YELLOW}[Remote]{_C.RESET} {cmd_text}")
            _execute_remote_command(session, cmd, args, respond)

    # Start background thread to drain remote commands while agent is idle
    _start_remote_drain_thread(session)

    # ── Main loop ────────────────────────────────────────
    while True:
        try:
            if session.has_project:
                prompt_text = f"urika:{session.project_name}> "
            else:
                prompt_text = "urika> "

            _drain_remote_queue(session)

            user_input = prompt_session.prompt(prompt_text).strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                _handle_command(session, user_input)
            else:
                _handle_free_text(session, user_input)

            _drain_remote_queue(session)

        except (EOFError, KeyboardInterrupt):
            if session.notification_bus is not None:
                try:
                    session.notification_bus.stop()
                except Exception:
                    pass
            session.save_usage()
            click.echo("\n  Goodbye.")
            break
        except SystemExit:
            if session.notification_bus is not None:
                try:
                    session.notification_bus.stop()
                except Exception:
                    pass
            session.save_usage()
            break


def _handle_command(session: ReplSession, text: str) -> None:
    """Parse and execute a slash command."""
    parts = text[1:].split(" ", 1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    all_cmds = get_all_commands(session)
    if cmd_name not in all_cmds:
        if cmd_name in PROJECT_COMMANDS and not session.has_project:
            print_error("Load a project first: /project <name>")
        else:
            print_error(f"Unknown command: /{cmd_name}. Type /help for commands.")
        return

    handler = all_cmds[cmd_name]["func"]
    try:
        handler(session, args)
    except SystemExit as exc:
        if exc.code == 0:
            raise  # Clean quit — let it propagate
        click.echo("\n  Cancelled.")
    except click.Abort:
        click.echo("\n  Cancelled.")
    except Exception as exc:
        print_error(f"Error: {exc}")


def _handle_free_text(session: ReplSession, text: str) -> None:
    """Send free text to the advisor agent."""
    if not session.has_project:
        click.echo("  Load a project first: /project <name>")
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

        # Build context — inject rolling summary from previous sessions
        from urika.core.advisor_memory import load_context_summary

        context = f"Project: {session.project_name}\n"
        context_summary = load_context_summary(session.project_path)
        if context_summary:
            context += (
                f"\n## Research Context (from previous sessions)\n\n"
                f"{context_summary}\n\n"
            )
        conv = session.get_conversation_context()
        if conv:
            context += f"\nPrevious conversation:\n{conv}\n"
        context += f"\nUser: {text}\n"

        # Load project state
        methods_path = session.project_path / "methods.json"
        if methods_path.exists():
            try:
                mdata = json.loads(methods_path.read_text(encoding="utf-8"))
                mlist = mdata.get("methods", [])
                context += f"\n{len(mlist)} methods tried.\n"
            except Exception:
                pass

        config = advisor.build_config(
            project_dir=session.project_path, experiment_id=""
        )
        config.max_turns = 25  # Standalone chat needs more turns than in-loop advisor

        _on_msg = _make_on_message()

        print_agent("advisor_agent")
        session.set_agent_active("advisor")
        try:
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
        finally:
            session.set_agent_idle()

        # Track usage
        session.record_agent_call(
            tokens_in=getattr(result, "tokens_in", 0) or 0,
            tokens_out=getattr(result, "tokens_out", 0) or 0,
            cost_usd=result.cost_usd or 0.0,
            model=getattr(result, "model", "") or "",
        )

        if result.success and result.text_output:
            click.echo(format_agent_output(result.text_output))
            session.add_message("user", text)
            session.add_message("advisor", result.text_output.strip())

            # Save to persistent advisor history
            from urika.core.advisor_memory import append_exchange

            advisor_text = result.text_output.strip()
            append_exchange(
                session.project_path, role="user", text=text, source="repl"
            )

            # Parse suggestions for saving alongside advisor response
            from urika.orchestrator.parsing import parse_suggestions

            parsed = parse_suggestions(advisor_text)
            parsed_suggestions = (
                parsed["suggestions"]
                if parsed and parsed.get("suggestions")
                else None
            )
            append_exchange(
                session.project_path,
                role="advisor",
                text=advisor_text,
                source="repl",
                suggestions=parsed_suggestions,
            )

            # Update rolling context summary (best-effort)
            try:
                from urika.core.advisor_memory import update_context_summary

                asyncio.run(
                    update_context_summary(
                        session.project_path, runner, registry
                    )
                )
            except Exception:
                pass

            # Send advisor response to remote channel if applicable
            if session._is_remote_command and session._remote_respond:
                from urika.notifications.bus import _split_message
                clean_text = _strip_json_blocks(advisor_text)
                for chunk in _split_message(clean_text, max_len=4000):
                    session._remote_respond(chunk)

            # Parse suggestions and offer to run them (skip for remote)
            if not session._is_remote_command:
                _offer_to_run_suggestions(session, result.text_output)
        else:
            print_error(f"Advisor error: {result.error}")

    except ImportError:
        print_error("Claude Agent SDK not installed.")
    except Exception as exc:
        print_error(f"Error: {exc}")


def _offer_to_run_suggestions(session: ReplSession, advisor_output: str) -> None:
    """Parse advisor suggestions and offer to start a run."""
    from urika.orchestrator.parsing import parse_suggestions

    parsed = parse_suggestions(advisor_output)
    if not parsed or not parsed.get("suggestions"):
        return

    suggestions = parsed["suggestions"]
    session.pending_suggestions = suggestions

    # Show what was suggested
    from urika.cli_display import _C

    click.echo(
        f"  {_C.BOLD}The advisor suggested {len(suggestions)} experiment(s):{_C.RESET}"
    )
    for i, s in enumerate(suggestions, 1):
        name = s.get("name", f"experiment-{i}")
        click.echo(f"    {i}. {name}")
    click.echo()

    try:
        from urika.repl_commands import _prompt_numbered

        choice = _prompt_numbered(
            "  Run these experiments?",
            [
                "Yes \u2014 start running now",
                "No \u2014 I'll run later with /run",
            ],
            default=1,
        )
        if choice.startswith("Yes"):
            from urika.repl_commands import cmd_run as _cmd_run

            _cmd_run(session, "")
    except click.Abort:
        pass


# ── Remote command execution ─────────────────────────────────

# Map remote command names to REPL handler functions
_REMOTE_COMMAND_MAP = {
    "run": cmd_run,
    "advisor": cmd_advisor,
    "evaluate": cmd_evaluate,
    "plan": cmd_plan,
    "report": cmd_report,
    "present": cmd_present,
    "finalize": cmd_finalize,
    "build-tool": cmd_build_tool,
    "resume": cmd_resume,
}


def _execute_remote_command(
    session: ReplSession,
    command: str,
    args: str,
    respond: object | None,
) -> None:
    """Execute a remote command through the REPL command handlers.

    Sets session._is_remote_command so handlers can skip interactive
    prompts and run with defaults. Sends completion/error back via
    the respond callback if provided.
    """
    handler = _REMOTE_COMMAND_MAP.get(command)
    if handler is None:
        msg = f"Unknown remote command: /{command}"
        click.echo(f"  {msg}")
        if respond:
            respond(msg)
        return

    session._is_remote_command = True
    session._remote_respond = respond
    try:
        handler(session, args)
        if respond:
            respond(f"/{command} completed.")
    except click.Abort:
        click.echo("\n  Cancelled.")
        if respond:
            respond(f"/{command} cancelled.")
    except Exception as exc:
        print_error(f"Error: {exc}")
        if respond:
            respond(f"/{command} error: {exc}")
    finally:
        session._is_remote_command = False
        session._remote_respond = None


def _start_remote_drain_thread(session: ReplSession) -> None:
    """Start a daemon thread that drains remote commands when REPL is idle.

    Checks the queue every 2 seconds. When the REPL is not running an
    agent command, pops the next queued command and executes it through
    the standard REPL command handlers.
    """

    def _drain_loop() -> None:
        while True:
            try:
                if (
                    not session.agent_active
                    and not session._is_remote_command
                    and session.has_remote_command
                ):
                    item = session.pop_remote_command()
                    if item is not None:
                        cmd, args, respond = item
                        cmd_text = f"/{cmd} {args}".strip()
                        click.echo(
                            f"\n  {_C.YELLOW}[Remote]{_C.RESET} {cmd_text}"
                        )
                        _execute_remote_command(session, cmd, args, respond)
            except Exception:
                logger.debug("Remote drain error", exc_info=True)
            time.sleep(2)

    thread = threading.Thread(
        target=_drain_loop, name="urika-remote-drain", daemon=True
    )
    thread.start()
