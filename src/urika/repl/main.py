"""Interactive REPL shell for Urika.

Provides a prompt_toolkit-based shell with tab completion,
command history, and a status toolbar. Agent commands block
the input loop during execution (Phase B will add async input).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import TYPE_CHECKING

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
    print_error,
    print_header,
)
from urika.repl.commands import (
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
from urika.repl.session import ReplSession

if TYPE_CHECKING:
    from urika.orchestrator.chat import OrchestratorChat

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


AGENT_COMMANDS = {
    "run", "evaluate", "plan", "advisor", "report",
    "present", "finalize", "build-tool", "resume",
}


async def _async_repl_loop(
    session: ReplSession,
    prompt_session: PromptSession,
    _drain_remote_queue,
) -> None:
    """Async REPL main loop — allows background threads to print.

    Agent commands (those in AGENT_COMMANDS) run in background threads
    so the user can continue typing while they execute. Free text typed
    while an agent is running is queued for injection into the next call.
    """
    from prompt_toolkit.patch_stdout import patch_stdout

    with patch_stdout():
        while True:
            try:
                if session.has_project:
                    prompt_text = f"urika:{session.project_name}> "
                else:
                    prompt_text = "urika> "

                _drain_remote_queue(session)

                user_input = (await prompt_session.prompt_async(prompt_text)).strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    parts = user_input[1:].split(" ", 1)
                    cmd_name = parts[0].lower()

                    if cmd_name in AGENT_COMMANDS:
                        if session.agent_active:
                            click.echo(
                                "  An agent is already running. "
                                "Use /stop to cancel."
                            )
                            continue
                        # Run agent command in a background thread
                        def _run_agent(cmd=user_input):
                            try:
                                _handle_command(session, cmd)
                            finally:
                                session.set_agent_inactive()

                        session.set_agent_active(cmd_name)
                        thread = threading.Thread(
                            target=_run_agent, daemon=True
                        )
                        thread.start()
                    else:
                        # Instant commands run on the main thread
                        _handle_command(session, user_input)
                else:
                    # Free text
                    if session.agent_active:
                        # Agent is running — queue input for injection
                        session.queue_input(user_input)
                        click.echo(
                            f"  {_C.DIM}> {user_input} "
                            f"(queued for {session.active_command})"
                            f"{_C.RESET}"
                        )
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


def run_repl() -> None:
    """Main REPL entry point."""
    session = ReplSession()
    history = InMemoryHistory()
    completer = UrikaCompleter(session)

    from urika.repl.commands import get_global_stats

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

    # ── Main loop (async for concurrent input/output) ────
    try:
        asyncio.run(_async_repl_loop(session, prompt_session, _drain_remote_queue))
    except (EOFError, KeyboardInterrupt):
        session.save_usage()
        click.echo("\n  Goodbye.")


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

    # Block agent commands when private endpoint is unreachable
    _AGENT_COMMANDS = {
        "run", "evaluate", "plan", "advisor", "report",
        "present", "finalize", "build-tool", "resume",
    }
    if cmd_name in _AGENT_COMMANDS and not session._private_endpoint_ok:
        click.echo(
            "  \u2717 Agent commands disabled \u2014 local model unreachable "
            "in hybrid/private mode."
        )
        click.echo(
            "    Start your local model or switch to open: /config"
        )
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


_orchestrator: "OrchestratorChat | None" = None


def _get_orchestrator(session: ReplSession) -> "OrchestratorChat":
    """Get or create the chat orchestrator, synced to current project."""
    global _orchestrator
    if _orchestrator is None:
        from urika.orchestrator.chat import OrchestratorChat

        _orchestrator = OrchestratorChat(project_dir=session.project_path)
    elif session.project_path and _orchestrator.project_dir != session.project_path:
        _orchestrator.set_project(session.project_path)
    return _orchestrator


def _handle_free_text(session: ReplSession, text: str) -> None:
    """Send free text to the chat orchestrator."""
    if not session._private_endpoint_ok:
        click.echo(
            "  \u2717 Agent commands disabled \u2014 local model unreachable "
            "in hybrid/private mode."
        )
        return

    orchestrator = _get_orchestrator(session)

    try:
        # Run in a separate thread since we're inside an async event loop
        import concurrent.futures

        session.set_agent_active("chat")
        print("  Thinking...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: asyncio.run(orchestrator.chat(text)))
            response = future.result()

        session.set_agent_inactive()
        print()
        print(format_agent_output(response))
        print()

        # Update session conversation for context
        session.add_message("user", text)
        session.add_message("assistant", response[:500])

        # Save session
        if session.project_path:
            try:
                from urika.core.orchestrator_sessions import (
                    save_session,
                    create_new_session,
                )

                # Get or create session data
                if not hasattr(session, "_orch_session") or session._orch_session is None:
                    session._orch_session = create_new_session()
                orch_session = session._orch_session
                orch_session.recent_messages = orchestrator.get_messages()
                if not orch_session.preview:
                    orch_session.preview = text[:80]
                save_session(session.project_path, orch_session)
            except Exception:
                pass  # Session persistence is best-effort
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
