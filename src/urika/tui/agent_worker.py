"""Background agent execution via Textual Workers.

Two execution modes for slash commands:

1. **Worker mode** — for long-running agent commands (``/run``,
   ``/finalize``, ``/evaluate``, etc.) that invoke Claude agents.
   Runs the handler in a Textual thread-based Worker so the TUI
   stays responsive. Output is captured to the OutputPanel.

2. **Suspend mode** — for interactive commands (``/config``,
   ``/notifications``, ``/new``) that use ``click.prompt`` /
   ``input()`` for user interaction. Textual's ``app.suspend()``
   temporarily releases the terminal so the command runs with real
   stdin/stdout. When the command finishes, Textual resumes and the
   TUI is redrawn. No fake stdin, no queue bridging, no escape
   sequence leaking.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Callable

from textual.worker import Worker

if TYPE_CHECKING:
    from urika.repl.session import ReplSession
    from urika.tui.app import UrikaApp


CommandHandler = Callable[["ReplSession", str], None]


def run_command_in_worker(
    app: UrikaApp,
    handler: CommandHandler,
    args: str,
    cmd_name: str,
) -> Worker:
    """Run a sync command handler in a background Textual Worker.

    For long-running agent commands. Output is captured to the
    OutputPanel via OutputCapture. The handler runs in a background
    thread so the TUI stays responsive.
    """
    from urika.cli_display import print_error
    from urika.tui.capture import OutputCapture
    from urika.tui.widgets.input_bar import InputBar

    def _post_command_refresh() -> None:
        from textual.css.query import NoMatches

        try:
            input_bar = app.query_one(InputBar)
        except NoMatches:
            return
        input_bar.refresh_prompt()

    def _work() -> None:
        app.session.set_agent_running(agent_name=cmd_name)
        try:
            with OutputCapture(app):
                try:
                    handler(app.session, args)
                except SystemExit:
                    app.session.save_usage()
                    app.call_from_thread(app.exit)
                except Exception as exc:
                    print_error(f"Error: {exc}")
        finally:
            app.session.set_agent_idle()
            try:
                app.call_from_thread(_post_command_refresh)
            except RuntimeError:
                pass

    return app.run_worker(_work, thread=True, name=f"agent:{cmd_name}")


def run_command_suspended(
    app: UrikaApp,
    handler: CommandHandler,
    args: str,
    cmd_name: str,
) -> None:
    """Run an interactive command with full terminal access.

    Uses ``app.suspend()`` to temporarily release the terminal from
    Textual, giving the command real stdin/stdout. The handler runs
    in a **thread** inside the suspend block — this is critical
    because ``app.suspend()`` releases the terminal but NOT the
    event loop. If the handler ran directly on the event loop
    thread, any ``asyncio.run()`` call inside it would crash with
    "cannot be called from a running event loop". The thread has
    no event loop, so ``asyncio.run()`` works. And since we're
    inside ``suspend()``, ``click.prompt()`` / ``input()`` read
    from the real terminal.

    ``thread.join()`` blocks until the handler finishes, keeping
    the suspend block open. When the thread exits, we prompt
    "Press Enter to return to the TUI..." so the user can read
    the output, then the suspend block closes and Textual resumes.
    """
    import threading

    from urika.cli_display import print_error

    try:
        with app.suspend():
            print()

            error_holder: list[str] = []

            def _run() -> None:
                try:
                    handler(app.session, args)
                except SystemExit:
                    app.session.save_usage()
                except Exception as exc:
                    error_holder.append(str(exc))
                    print_error(f"Error: {exc}")

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            thread.join()

            print()
            input("Press Enter to return to the TUI...")
    except Exception:
        pass
