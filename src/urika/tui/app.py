"""Main Textual application for Urika."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.repl.session import ReplSession
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
        # One capture factory per app; entering `with self._capture:`
        # activates it for a single handler invocation. NOT reentrant —
        # never nest `with self._capture:` blocks.
        self._capture = OutputCapture(self)

    def compose(self) -> ComposeResult:
        yield OutputPanel()
        yield InputBar(self.session)
        yield StatusBar(self.session)
        yield Footer()

    def on_mount(self) -> None:
        """Show welcome message on startup."""
        panel = self.query_one(OutputPanel)
        panel.write_line("Welcome to Urika. Type /help for commands.")

    @on(InputBar.CommandSubmitted)
    def _on_command(self, event: InputBar.CommandSubmitted) -> None:
        """Dispatch user input to command handlers, queue, or free-text path."""
        text = event.value
        if text.startswith("/"):
            self._dispatch_command(text)
        elif self.session.agent_running:
            # Task 8 drains this queue when the worker picks up the
            # next turn. For now, just confirm receipt in the panel.
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

        # /quit is handled inline — there is no "quit" in repl.commands
        # (the old REPL handled it in its main loop).
        if cmd_name == "quit":
            self.session.save_usage()
            self.exit()
            return

        from urika.cli_display import print_error
        from urika.repl.commands import PROJECT_COMMANDS, get_all_commands

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:
            # Refine the error message if the user hit a project-only
            # command without a project loaded — get_all_commands
            # already filters those out, so we reach here either way.
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
                # A handler calling sys.exit() should close the app
                # rather than propagate and crash the event loop.
                self.session.save_usage()
                self.exit()
            except Exception as exc:
                # Not a silent swallow — the error is printed through
                # OutputCapture so the user sees it and can recover.
                print_error(f"Error: {exc}")

        # A command like /project mutates session.project_name, which
        # changes the prompt text and the suggester list. Refresh
        # unconditionally — cheap and keeps state consistent.
        input_bar = self.query_one(InputBar)
        input_bar.refresh_prompt()

    def _dispatch_free_text(self, text: str) -> None:
        """Send free text to the advisor / chat orchestrator."""
        if not self.session.has_project:
            panel = self.query_one(OutputPanel)
            panel.write_line("  Load a project first: /project <name>")
            return
        # Synchronous for now — Task 8 moves this onto a Textual Worker
        # so the UI stays responsive while the orchestrator is thinking.
        from urika.repl import _handle_free_text

        with self._capture:
            _handle_free_text(self.session, text)

    def action_cancel_agent(self) -> None:
        """Cancel the running agent on Ctrl+C."""
        if self.session.agent_running:
            self.session.set_agent_idle(error="Cancelled by user")
            panel = self.query_one(OutputPanel)
            panel.write_line("  Agent cancelled.")

    def action_quit_app(self) -> None:
        """Quit on Ctrl+D."""
        self.session.save_usage()
        self.exit()
