"""Background agent execution via Textual Workers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.worker import Worker

if TYPE_CHECKING:
    from urika.tui.app import UrikaApp


def run_command_in_worker(
    app: UrikaApp,
    handler: object,
    args: str,
) -> Worker:
    """Run a command handler in a background Textual Worker.

    This allows the input bar to stay responsive while agents execute.
    The handler's stdout/stderr is captured and routed to the output panel.
    """
    from urika.tui.capture import OutputCapture
    from urika.cli_display import print_error

    def _work() -> None:
        capture = OutputCapture(app)
        with capture:
            try:
                handler(app.session, args)
            except SystemExit:
                app.call_from_thread(app.exit)
            except Exception as exc:
                print_error(f"Error: {exc}")
        app.call_from_thread(_post_command_refresh)

    def _post_command_refresh() -> None:
        from urika.tui.widgets.input_bar import InputBar

        try:
            input_bar = app.query_one(InputBar)
            input_bar.refresh_prompt()
        except Exception:
            pass

    return app.run_worker(_work, thread=True)
