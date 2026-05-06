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
    # v0.4.2 Package J: ``summarize`` (added in v0.4.2 H8) is also a
    # multi-minute agent call; without it in this set the REPL ran
    # /summarize on the main thread and blocked the prompt for the
    # duration with no way to /stop. The TUI already lists it in
    # ``_WORKER_COMMANDS``.
    "summarize",
}

# Commands that use interactive prompts and need their own thread
# (they call asyncio.run or prompt_toolkit internally)
INTERACTIVE_COMMANDS = {
    "config", "setup", "update", "new",
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
                elif cmd_name in INTERACTIVE_COMMANDS:
                    # Interactive commands need their own thread
                    def _run_interactive(cmd=user_input):
                        _handle_command(session, cmd)

                    thread = threading.Thread(
                        target=_run_interactive, daemon=True
                    )
                    thread.start()
                    thread.join()
                else:
                    # Instant commands run on the main thread
                    _handle_command(session, user_input)
            else:
                # Free text
                if session.agent_active:
                    # Agent is running — queue input for injection
                    session.queue_input(user_input)
                    click.echo(
                        f"  > {user_input} "
                        f"(queued for {session.active_command})"
                    )
                else:
                    # Run chat in background thread so prompt stays active
                    def _run_chat(msg=user_input):
                        try:
                            _handle_free_text(session, msg)
                        finally:
                            session.set_agent_inactive()

                    session.set_agent_active("chat")
                    thread = threading.Thread(
                        target=_run_chat, daemon=True
                    )
                    thread.start()

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

    # Set default model from SDK so the footer shows it from startup
    try:
        from urika.agents.runner import get_runner
        runner = get_runner()
        session.model = getattr(runner, "default_model", "") or "claude-agent-sdk"
    except Exception:
        session.model = "claude-agent-sdk"

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
    # Cache holds (mode, broken) where ``broken`` is True when the
    # project's privacy mode requires a private endpoint but none is
    # configured (project-local OR globally). When broken, the toolbar
    # paints the mode red so the user notices before runs hard-fail.
    _privacy_cache: dict[str, tuple[str, bool]] = {}

    def _get_privacy(project_path) -> tuple[str, bool]:
        key = str(project_path)
        if key not in _privacy_cache:
            try:
                from urika.agents.config import load_runtime_config

                rc = load_runtime_config(project_path)
                mode = rc.privacy_mode
                broken = False
                if mode in ("private", "hybrid"):
                    # rc.endpoints already merges project + globals
                    # (commit 1 of project-consistency phase).
                    has_usable = any(
                        (ep.base_url or "").strip()
                        for ep in rc.endpoints.values()
                    )
                    broken = not has_usable
                _privacy_cache[key] = (mode, broken)
            except Exception:
                _privacy_cache[key] = ("open", False)
        return _privacy_cache[key]

    # Spinner for the toolbar — rotates when agent is active
    _spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _spinner_idx = [0]

    # Activity verbs that rotate during agent work
    _activity_verbs = [
        "Thinking", "Reasoning", "Analyzing", "Processing",
        "Exploring", "Evaluating", "Considering", "Reviewing",
    ]
    _verb_idx = [0]
    _last_verb_time = [0.0]

    def _bottom_toolbar():
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80

        D = "\033[2m"   # dim
        R = "\033[0m"   # reset
        sep = f"{D} \u2502 {R}"  # │ separator

        lines = []

        # ── Line 1: Activity line ──
        line1_parts = [f"{D}" + "\u2500" * cols + f"{R}\n"]

        if session.agent_active:
            # Spinner
            frame = _spinner_frames[_spinner_idx[0] % len(_spinner_frames)]
            _spinner_idx[0] += 1

            # Rotate verb every 3 seconds
            now = time.monotonic()
            if now - _last_verb_time[0] > 3.0:
                _verb_idx[0] = (_verb_idx[0] + 1) % len(_activity_verbs)
                _last_verb_time[0] = now
            verb = _activity_verbs[_verb_idx[0]]

            agent_name = session.active_command or "agent"
            line1_parts.append(f" \033[36m{frame}\033[0m")
            line1_parts.append(f" \033[33;1m{agent_name}\033[0m")
            line1_parts.append(f" {D}\u2014 {verb}\u2026{R}")

            if session.agent_name:
                line1_parts.append(f"{sep}\033[33m{session.agent_name}\033[0m")
            if hasattr(session, "experiment_id") and session.experiment_id:
                line1_parts.append(f"{sep}{D}{session.experiment_id}{R}")
        else:
            line1_parts.append(f" {D}ready{R}")

        lines.append("".join(line1_parts))

        # ── Line 2: Status line (always shown) ──
        line2_parts = []
        line2_parts.append(" \033[34;1murika\033[0m")

        if session.has_project:
            line2_parts.append(f"{sep}\033[36m{session.project_name}\033[0m")
            privacy, broken = _get_privacy(session.project_path)
            if broken:
                # Red + bold + warning glyph: project's mode requires a
                # private endpoint but none is configured anywhere. Runs
                # will hard-fail until the user sets one.
                line2_parts.append(
                    f"{sep}\033[31;1m{privacy} ⚠ no endpoint\033[0m"
                )
            else:
                line2_parts.append(f"{sep}\033[33m{privacy}\033[0m")

        if session.model:
            from urika.cli_display import format_model_source
            model_display = format_model_source(
                session.model, project_dir=session.project_path,
            )
            line2_parts.append(f"{sep}\033[36m{model_display}\033[0m")

        elapsed = _format_duration(session.elapsed_ms)
        line2_parts.append(f"{sep}\033[35m{elapsed}\033[0m")

        tokens = session.total_tokens_in + session.total_tokens_out
        tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
        line2_parts.append(f"{sep}{D}{tok_str} tokens \u00b7 {session.agent_calls} calls{R}")
        if session.total_cost_usd > 0:
            line2_parts.append(f"{sep}\033[32m~${session.total_cost_usd:.2f}\033[0m")
        else:
            line2_parts.append(f"{sep}{D}$0.00{R}")

        lines.append("".join(line2_parts))

        return ANSI("\n".join(lines))

    custom_style = Style.from_dict({"bottom-toolbar": "noreverse"})

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        bottom_toolbar=_bottom_toolbar,
        style=custom_style,
    )

    # Background thread to refresh the toolbar spinner when agent is active
    def _toolbar_refresh():
        while True:
            time.sleep(0.2)  # 5 Hz refresh
            if session.agent_active and prompt_session.app:
                try:
                    prompt_session.app.invalidate()
                except Exception:
                    pass

    _refresh_thread = threading.Thread(target=_toolbar_refresh, daemon=True)
    _refresh_thread.start()

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
        # Already running in a background thread (from _async_repl_loop)
        # so we can use asyncio.run() safely here
        from urika.cli_display import print_tool_use

        def _stream_output(kind: str, content: str) -> None:
            """Print agent activity as it streams — same style as CLI agents."""
            if kind == "tool":
                # Show tool use: Read, Bash, Glob, Grep — real-time
                parts = content.split(": ", 1)
                tool_name = parts[0]
                detail = parts[1] if len(parts) > 1 else ""
                print_tool_use(tool_name, detail)

        result = asyncio.run(orchestrator.chat(text, on_output=_stream_output))
        response = result.get("response", "")

        # Update session usage stats (shown in toolbar)
        session.total_tokens_in += result.get("tokens_in", 0)
        session.total_tokens_out += result.get("tokens_out", 0)
        session.total_cost_usd += result.get("cost_usd", 0)
        session.agent_calls += 1
        if result.get("model"):
            session.model = result["model"]

        click.echo()
        click.echo(format_agent_output(response))
        click.echo()

        # Update session conversation for context
        session.add_message("user", text)
        session.add_message("assistant", response[:500])

        # v0.4.2 (Package I): parse advisor/orchestrator suggestions out of
        # the response so /run picks them up via session.pending_suggestions.
        # Pre-fix the REPL had ``_offer_to_run_suggestions`` defined a few
        # lines below but never called it from this path — so the REPL had
        # the same advisor->run silent-fail-to-pending bug the TUI was
        # found to have. We use the silent-store form (matches the TUI's
        # behaviour from Package H) rather than the interactive offer to
        # avoid prompting mid-stream; users still get a one-line hint
        # to type /run.
        try:
            from urika.orchestrator.parsing import parse_suggestions

            parsed = parse_suggestions(response)
            if parsed and parsed.get("suggestions"):
                session.pending_suggestions = parsed["suggestions"]
                n = len(session.pending_suggestions)
                click.echo(
                    f"  ✨ {n} experiment suggestion(s) captured. "
                    f"Type /run to start."
                )
        except Exception:
            # Suggestion parsing is best-effort — never let it break chat.
            pass

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

# Hardcoded list of slash commands that are NOT routable from
# Slack/Telegram (interactive editors, destructive admin actions, or
# stuff that doesn't make sense remotely).
_REMOTE_BLOCKED_COMMANDS = frozenset(
    {
        "quit",        # remote can't quit the local TUI process
        "copy",        # clipboard is local-only
        "new",         # spawns the project-builder agent loop
        "config",      # interactive prompts beyond /config show
        "notifications",  # interactive prompts
        "setup",       # first-run interactive wizard
        "memory",      # /memory add opens click.edit (no editor remotely)
        "delete",      # destructive — gate behind explicit local action
        "delete-experiment",  # same
    }
)


def _build_remote_command_map() -> dict:
    """Resolve the slash registry to a remote-callable handler map.

    v0.4.2 Package J: pre-fix this was a hardcoded list of 9 names
    that drifted away from the live registry — every new slash added
    in v0.4.2 (/setup, /summarize, /sessions, /memory, /venv,
    /experiment-create) was silently unreachable from Slack/Telegram.
    Now we union ``GLOBAL_COMMANDS`` and ``PROJECT_COMMANDS`` and
    drop only the explicit ``_REMOTE_BLOCKED_COMMANDS`` so new slashes
    are remote-callable by default.
    """
    from urika.repl.commands_registry import (
        GLOBAL_COMMANDS,
        PROJECT_COMMANDS,
    )

    out: dict = {}
    for name, entry in {**GLOBAL_COMMANDS, **PROJECT_COMMANDS}.items():
        if name in _REMOTE_BLOCKED_COMMANDS:
            continue
        out[name] = entry["func"]
    return out


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
    remote_map = _build_remote_command_map()
    handler = remote_map.get(command)
    if handler is None:
        if command in _REMOTE_BLOCKED_COMMANDS:
            msg = (
                f"/{command} is not available remotely "
                f"(interactive or destructive — run it locally)."
            )
        else:
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
