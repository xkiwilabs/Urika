"""Main Textual application for Urika."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Footer

from urika.orchestrator.chat import OrchestratorChat
from urika.repl.session import ReplSession
from urika.tui.agent_worker import run_command_in_worker
from urika.tui.capture import OutputCapture
from urika.tui.widgets.input_bar import InputBar
from urika.tui.widgets.output_panel import OutputPanel
from urika.tui.widgets.status_bar import StatusBar

# Commands that invoke a Claude agent and can take minutes. These run
# on a background thread-worker so the TUI stays responsive. Kept as a
# module constant so tests and future dispatch code share one source of
# truth. Order doesn't matter — membership check only.
_BLOCKING_COMMANDS = frozenset(
    {
        "run",
        "finalize",
        "evaluate",
        "plan",
        "advisor",
        "present",
        "report",
        "build-tool",
        "new",
    }
)

# Escape hatches that remain usable even while an agent is running.
# /quit must always work so the user can get out; /stop is reserved for
# a future cancellation path (Task 8's action_cancel_agent is the stub).
_ALWAYS_ALLOWED_COMMANDS = frozenset({"quit", "stop"})


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
        # Lazy orchestrator — created when first free-text lands, reused
        # across turns so conversation history is preserved. Reset if
        # the project changes.
        self._orchestrator: OrchestratorChat | None = None

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
        """Parse and execute a slash command.

        Three routes:

        * ``/quit`` — handled inline (no entry in the commands registry).
        * Blocking commands (agent-invoking) — dispatched to a
          thread-based worker via :func:`run_command_in_worker`. While
          a worker is active, new blocking commands are rejected with
          a busy hint; only ``/quit`` and ``/stop`` remain usable.
        * Everything else — executed inline under ``self._capture``.
        """
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

        # Busy guard: while an agent worker is running, reject new
        # blocking commands before they can race the live OutputCapture
        # (which is NOT reentrant). Escape hatches are whitelisted.
        if (
            self.session.agent_running
            and cmd_name not in _ALWAYS_ALLOWED_COMMANDS
            and cmd_name in _BLOCKING_COMMANDS
        ):
            with self._capture:
                print_error(
                    f"Agent busy running /{self.session.agent_name or 'command'}"
                    " — wait or use /stop"
                )
            return

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:
            # Refine the error message if the user hit a project-only
            # command without a project loaded — get_all_commands
            # already filters those out, so we reach here either way.
            # Single `with self._capture:` block so future branches
            # can't accidentally skip the capture wrapper.
            with self._capture:
                if cmd_name in PROJECT_COMMANDS and not self.session.has_project:
                    print_error("Load a project first: /project <name>")
                else:
                    print_error(
                        f"Unknown command: /{cmd_name}. Type /help for commands."
                    )
            return

        handler = all_cmds[cmd_name]["func"]

        # Blocking commands run on a background thread worker. The
        # worker manages its own OutputCapture, session.agent_running
        # lifecycle, and prompt refresh — so we just hand off and return.
        if cmd_name in _BLOCKING_COMMANDS:
            run_command_in_worker(self, handler, args, cmd_name)
            return

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
        """Send free text to the chat orchestrator on a Textual Worker.

        Must NOT call the REPL's `_handle_free_text` synchronously —
        that function wraps `asyncio.run(orchestrator.chat(...))`, which
        raises RuntimeError when called from an already-running event
        loop (which Textual always has). Instead, schedule an async
        coroutine worker that awaits `orchestrator.chat` directly.
        Task 8 will extend this to full agent-command workers with
        cancellation; Task 7 only needs the chat path.
        """
        if not self.session.has_project:
            panel = self.query_one(OutputPanel)
            panel.write_line("  Load a project first: /project <name>")
            return
        self.run_worker(self._run_free_text(text), name="free_text")

    async def _run_free_text(self, text: str) -> None:
        """Worker coroutine: run the orchestrator and display its reply.

        Runs inside Textual's event loop, so `orchestrator.chat` is
        awaited naturally. Session bookkeeping (tokens, cost, model,
        conversation history) mirrors the REPL's `_handle_free_text`
        so the two paths stay observably equivalent.
        """
        from urika.cli_display import format_agent_output

        # Create-or-reuse orchestrator. Reset when the project changes
        # so we don't bleed context between projects.
        if (
            self._orchestrator is None
            or self._orchestrator.project_dir != self.session.project_path
        ):
            self._orchestrator = OrchestratorChat(project_dir=self.session.project_path)
        orch = self._orchestrator

        self.session.set_agent_running(agent_name="chat")
        panel = self.query_one(OutputPanel)
        try:
            result = await orch.chat(text)
            response = result.get("response", "") or ""

            # Update session stats for the status bar.
            self.session.total_tokens_in += result.get("tokens_in", 0) or 0
            self.session.total_tokens_out += result.get("tokens_out", 0) or 0
            self.session.total_cost_usd += result.get("cost_usd", 0) or 0
            self.session.agent_calls += 1
            if result.get("model"):
                self.session.model = result["model"]

            panel.write_line("")
            panel.write_line(format_agent_output(response))
            panel.write_line("")

            self.session.add_message("user", text)
            self.session.add_message("assistant", response[:500])
        except Exception as exc:
            # Not a silent swallow — the error lands in the panel so the
            # user can see what went wrong.
            panel.write_line(f"  \u2717 Error: {exc}")
        finally:
            self.session.set_agent_idle()

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
