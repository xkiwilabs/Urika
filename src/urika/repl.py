"""Interactive REPL shell for Urika.

Provides a prompt_toolkit-based shell with tab completion,
command history, and a status toolbar. During agent execution,
keystrokes are captured silently and queued for the next agent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import termios
import threading
import tty

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style

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
        parts.append(
            "\033[2m" + "\u2500" * cols + "\033[0m\n"
        )
        parts.append(" \033[34;1murika\033[0m")
        if session.has_project:
            parts.append(
                f" \033[2m\u00b7 {session.project_name}\033[0m"
            )
            privacy = _get_privacy(session.project_path)
            if privacy != "open":
                parts.append(
                    f" \033[33m\u00b7 {privacy}\033[0m"
                )
        if session.model:
            parts.append(
                f" \033[36m\u00b7 {session.model}\033[0m"
            )
        elapsed = _format_duration(session.elapsed_ms)
        parts.append(f" \033[31m\u00b7 {elapsed}\033[0m")
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
                f" \033[2m\u00b7 {tok_str} tokens"
                f" \u00b7 {session.agent_calls} calls\033[0m"
            )
            if session.total_cost_usd > 0:
                parts.append(
                    f" \033[32m\u00b7"
                    f" ~${session.total_cost_usd:.2f}\033[0m"
                )
        return ANSI("".join(parts))

    custom_style = Style.from_dict(
        {"bottom-toolbar": "noreverse"}
    )

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        bottom_toolbar=_bottom_toolbar,
        style=custom_style,
    )

    # ── Main loop ────────────────────────────────────────
    while True:
        try:
            if session.has_project:
                prompt_text = (
                    f"urika:{session.project_name}> "
                )
            else:
                prompt_text = "urika> "

            user_input = prompt_session.prompt(
                prompt_text
            ).strip()

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


# Commands that invoke agents (long-running)
_BLOCKING_COMMANDS = {
    "run", "finalize", "evaluate", "plan", "advisor",
    "present", "report", "build-tool", "new",
}


class _InputCapture:
    """Captures input during agent execution without echoing mid-stream.

    Terminal is put in cbreak mode so individual keystrokes don't echo
    inline with agent output. But when the user presses Enter, the
    completed line is printed with a clear [queued] label so they can
    see what they typed and that it was received.
    """

    def __init__(self, session: ReplSession) -> None:
        self._session = session
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._old_settings: list | None = None

    def start(self) -> None:
        """Start capturing stdin in a background thread."""
        if not sys.stdin.isatty():
            return
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._capture_loop, daemon=True
            )
            self._thread.start()
        except (termios.error, OSError):
            self._old_settings = None

    def stop(self) -> None:
        """Stop capturing and restore terminal."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None
        if self._old_settings is not None:
            try:
                termios.tcsetattr(
                    sys.stdin,
                    termios.TCSADRAIN,
                    self._old_settings,
                )
            except (termios.error, OSError):
                pass
            self._old_settings = None

    def _capture_loop(self) -> None:
        """Read characters, show completed lines with [queued] label."""
        import select

        buf = ""
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select(
                    [sys.stdin], [], [], 0.1
                )
                if not ready:
                    continue
                ch = sys.stdin.read(1)
                if not ch:
                    continue
                if ch == "\n" or ch == "\r":
                    if buf.strip():
                        self._session.queue_input(buf.strip())
                        # Replace typing line with queued confirmation
                        sys.stdout.write(
                            f"\r\033[K  {_C.DIM}\u203a "
                            f"{buf.strip()}"
                            f"  [{_C.YELLOW}queued for advisor"
                            f"{_C.DIM}]{_C.RESET}\n"
                        )
                        sys.stdout.flush()
                    else:
                        sys.stdout.write("\r\033[K")
                        sys.stdout.flush()
                    buf = ""
                elif ch == "\x7f" or ch == "\x08":
                    buf = buf[:-1]
                    # Redraw typing line
                    sys.stdout.write(
                        f"\r\033[K  {_C.DIM}\u203a {_C.RESET}"
                        f"{buf}"
                    )
                    sys.stdout.flush()
                elif ch >= " ":
                    buf += ch
                    # Show character as typed
                    sys.stdout.write(
                        f"\r\033[K  {_C.DIM}\u203a {_C.RESET}"
                        f"{buf}"
                    )
                    sys.stdout.flush()
            except (OSError, ValueError):
                break
        # Flush remaining buffer
        if buf.strip():
            self._session.queue_input(buf.strip())
            sys.stdout.write(
                f"\r\033[K  {_C.DIM}\u203a "
                f"{buf.strip()}"
                f"  [{_C.YELLOW}queued"
                f"{_C.DIM}]{_C.RESET}\n"
            )
            sys.stdout.flush()


def _handle_command(session: ReplSession, text: str) -> None:
    """Parse and execute a slash command."""
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

    if cmd_name in _BLOCKING_COMMANDS:
        # Capture input silently during agent execution
        capture = _InputCapture(session)
        capture.start()
        try:
            handler(session, args)
        except Exception as exc:
            print_error(f"Error: {exc}")
        finally:
            capture.stop()
    else:
        try:
            handler(session, args)
        except Exception as exc:
            print_error(f"Error: {exc}")


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
