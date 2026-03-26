"""Main Textual application for Urika."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.repl_session import ReplSession
from urika.tui.capture import OutputCapture
from urika.tui.widgets.input_bar import InputBar
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar


class UrikaApp(App):
    """Urika TUI — three-zone interactive interface."""

    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    BINDINGS = [
        ("ctrl+c", "cancel_agent", "Cancel"),
        ("ctrl+d", "quit_app", "Quit"),
    ]

    def __init__(self, session: ReplSession | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.session = session or ReplSession()
        self._capture = OutputCapture(self)

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield InputBar(self.session)
        yield StatusBar(self.session)
        yield Footer()

    @on(InputBar.CommandSubmitted)
    def _on_command(self, event: InputBar.CommandSubmitted) -> None:
        """Dispatch user input to command handlers or advisor."""
        text = event.value
        if text.startswith("/"):
            self._dispatch_command(text)
        elif self.session.agent_running:
            self.session.queue_input(text)
            panel = self.query_one(OutputPanel)
            panel.write_line(f"  [queued] {text}")
        else:
            self._dispatch_free_text(text)

    def _dispatch_command(self, text: str) -> None:
        """Parse and execute a slash command."""
        parts = text[1:].split(" ", 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd_name == "quit":
            self.session.save_usage()
            self.exit()
            return

        from urika.repl_commands import PROJECT_COMMANDS, get_all_commands
        from urika.cli_display import print_error

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:
            if cmd_name in PROJECT_COMMANDS and not self.session.has_project:
                with self._capture:
                    print_error("Load a project first: /project <name>")
            else:
                with self._capture:
                    print_error(
                        f"Unknown command: /{cmd_name}. Type /help for commands."
                    )
            return

        handler = all_cmds[cmd_name]["func"]
        with self._capture:
            try:
                handler(self.session, args)
            except SystemExit:
                self.session.save_usage()
                self.exit()
            except Exception as exc:
                from urika.cli_display import print_error

                print_error(f"Error: {exc}")

        # Refresh input prompt after potential project change
        input_bar = self.query_one(InputBar)
        input_bar.refresh_prompt()

    def _dispatch_free_text(self, text: str) -> None:
        """Send free text to the advisor agent."""
        if not self.session.has_project:
            panel = self.query_one(OutputPanel)
            panel.write_line("  Load a project first: /project <name>")
            return
        # For now, run synchronously — Task 8 adds background workers
        from urika.repl import _handle_free_text

        with self._capture:
            _handle_free_text(self.session, text)

    def action_cancel_agent(self) -> None:
        """Cancel running agent on Ctrl+C."""
        if self.session.agent_running:
            self.session.set_agent_idle(error="Cancelled by user")
            panel = self.query_one(OutputPanel)
            panel.write_line("  Agent cancelled.")

    def action_quit_app(self) -> None:
        """Quit on Ctrl+D."""
        self.session.save_usage()
        self.exit()
