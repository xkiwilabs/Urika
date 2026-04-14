"""Background agent execution via Textual Workers.

Task 8: Blocking slash-command handlers (``/run``, ``/finalize``,
``/evaluate``, etc.) call Claude agents synchronously and can take
minutes. Running them on Textual's event-loop thread would freeze the
entire UI. :func:`run_command_in_worker` wraps such handlers in a
thread-based Textual Worker so the input bar, status bar, and output
panel all stay live while the agent runs.

The free-text path (user typing non-slash text with a project loaded)
is NOT routed through this function — it uses an async worker coroutine
in :mod:`urika.tui.app` because the orchestrator exposes an async
``chat()``. See :meth:`UrikaApp._dispatch_free_text` for that path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from textual.worker import Worker

if TYPE_CHECKING:
    from urika.repl.session import ReplSession
    from urika.tui.app import UrikaApp


# Type alias — handlers follow the REPL's ``(session, args)`` signature.
CommandHandler = Callable[["ReplSession", str], None]


def run_command_in_worker(
    app: UrikaApp,
    handler: CommandHandler,
    args: str,
    cmd_name: str,
) -> Worker:
    """Run a sync command handler in a background Textual Worker.

    The worker:

    1. Marks ``session.agent_running=True`` (with ``agent_name=cmd_name``)
       so the status bar shows activity and ``_on_command``'s queue
       branch intercepts user input while the handler runs.
    2. Enters a fresh :class:`OutputCapture` so the handler's ``print``
       and ``click.echo`` land in the :class:`OutputPanel`.
    3. Invokes ``handler(app.session, args)``. ``SystemExit`` routes to
       a clean ``app.exit()``; any other ``Exception`` is printed via
       ``print_error`` (which is still inside the capture, so the
       message lands in the panel, not on real stdout).
    4. On completion — success or failure — runs ``set_agent_idle()``
       and refreshes the input bar prompt via ``call_from_thread``.

    Two correctness notes worth preserving:

    * The capture context is NOT reentrant. Task 8's dispatch rejects
      new blocking commands while ``session.agent_running`` is True, so
      the main thread and the worker thread never race to install
      overlapping captures. See
      :meth:`urika.tui.app.UrikaApp._dispatch_command`.

    * The ``agent_running`` lifecycle runs in ``try/finally`` around
      the capture block, not outside the whole function, so an
      exception in :class:`OutputCapture.__enter__` (e.g. the nested-
      capture guard firing) still leaves the session in a clean idle
      state.
    """
    from urika.cli_display import print_error
    from urika.tui.capture import OutputCapture
    from urika.tui.widgets.input_bar import InputBar

    def _post_command_refresh() -> None:
        """Refresh input prompt on the Textual thread.

        Wrapped in NoMatches/AttributeError guards because this runs
        during app shutdown too — the widget tree may already be gone.
        """
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
                    # A handler invoking sys.exit() should close the
                    # app cleanly rather than crash the worker. Mirror
                    # the inline path's save_usage call so usage stats
                    # from a quitting handler aren't lost.
                    app.session.save_usage()
                    app.call_from_thread(app.exit)
                except Exception as exc:
                    # Not swallowed — print_error runs inside the
                    # capture block, so the message lands in the panel.
                    print_error(f"Error: {exc}")
        finally:
            app.session.set_agent_idle()
            # Schedule the prompt refresh on the event loop thread.
            try:
                app.call_from_thread(_post_command_refresh)
            except RuntimeError:
                # Event loop already gone (app shutting down).
                # Nothing more to refresh.
                pass

    return app.run_worker(_work, thread=True, name=f"agent:{cmd_name}")
