"""Main Textual application for Urika."""

from __future__ import annotations

from pathlib import Path

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

    # Absolute path so subclasses in tests (e.g. CapturingApp in
    # test_input_bar.py) don't resolve CSS relative to their own
    # __module__ directory and fail. Textual's default behavior is to
    # resolve a string CSS_PATH relative to the subclass's module,
    # which would break the moment anything subclasses UrikaApp.
    CSS_PATH = Path(__file__).parent / "urika.tcss"
    TITLE = "Urika"
    SUB_TITLE = "Multi-agent scientific analysis"

    BINDINGS = [
        # Ctrl+Q is the unambiguous quit binding — surfaced in the
        # Footer so users can see it at a glance. Ctrl+C still works
        # (cancels a running agent, or quits when idle — see
        # action_cancel_agent). Ctrl+D is an extra escape hatch but
        # Textual's terminal driver sometimes swallows it as EOF, so
        # we don't rely on it as the primary quit key.
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+c", "cancel_agent", "Cancel / Quit"),
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
        """Show the welcome header + global stats on startup.

        Lands in the OutputPanel as a normal sequence of RichLog
        lines. The ASCII header produced by
        :func:`urika.cli_display.print_header` is routed through
        :meth:`_run_with_panel_output` so the colored banner lines
        are captured into the panel. ``get_global_stats`` is wrapped
        in a narrow try/except so a fresh install with no projects
        file doesn't block the TUI — an empty welcome is better than
        a crash.
        """
        from urika.cli_display import print_header

        panel = self.query_one(OutputPanel)

        # ASCII banner — the same one the REPL/CLI print. Use the
        # capture helper so the colored print() calls inside
        # print_header() route to the panel rather than the raw
        # terminal (which isn't attached to anything Textual owns).
        self._run_with_panel_output(print_header)
        panel.write_line("  Urika — Multi-agent scientific analysis platform")
        panel.write_line("")

        try:
            from urika.repl.commands import get_global_stats

            stats = get_global_stats()
            panel.write_line(
                f"  {stats['projects']} projects · "
                f"{stats['experiments']} experiments · "
                f"{stats['methods']} methods · "
                f"{stats['sdk']}"
            )
        except (OSError, KeyError, ImportError) as exc:
            # Fresh install / missing stats files / partial import.
            # Log rather than silently swallow so real bugs surface.
            self.log.warning(f"welcome stats lookup failed: {exc}")

        panel.write_line("")
        panel.write_line(
            "  Type /help for commands, or just type to talk to the advisor."
        )
        panel.write_line("  Press Ctrl+Q to quit.")
        panel.write_line("")

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

    def _run_with_panel_output(self, func) -> None:
        """Run ``func`` so its stdout lands in the OutputPanel.

        Handles both capture-active and capture-inactive contexts. If
        the process ``sys.stdout`` is already a ``_TuiWriter`` (i.e.
        a worker thread installed one), call ``func`` directly — the
        existing writer is thread-safe and routes output to the panel
        via ``call_from_thread``. Otherwise, enter ``self._capture``
        briefly so the function's prints are captured.

        This replaces the older pattern of blindly doing
        ``with self._capture: ...`` which crashed when a worker was
        active (nested captures raise RuntimeError by design).
        """
        import sys

        from urika.tui.capture import _TuiWriter

        if isinstance(sys.stdout, _TuiWriter):
            func()
        else:
            with self._capture:
                func()

    def _dispatch_command(self, text: str) -> None:
        """Parse and execute a slash command.

        Three routes:

        * ``/quit`` — handled inline (no entry in the commands registry),
          always available.
        * Anything else while an agent worker is running — rejected with
          a busy hint, except ``/stop`` which writes a cooperative stop
          flag that the experiment runner polls.
        * Blocking commands (agent-invoking) — dispatched to a
          thread-based worker via :func:`run_command_in_worker`.
        * Everything else — executed inline via
          :meth:`_run_with_panel_output` which picks the right
          capture strategy based on runtime state.
        """
        parts = text[1:].split(" ", 1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # /quit is handled inline — there is no "quit" in repl.commands
        # (the old REPL handled it in its main loop). Always available.
        if cmd_name == "quit":
            self.session.save_usage()
            self.exit()
            return

        from urika.cli_display import print_error
        from urika.repl.commands import PROJECT_COMMANDS, get_all_commands

        busy_hint = (
            f"Agent busy running /{self.session.agent_name or 'command'}"
            " — wait or use /stop"
        )

        # Busy guard: while an agent worker is running, reject any
        # slash command that isn't an escape hatch. The hint is
        # printed via ``_run_with_panel_output`` which picks the
        # right capture strategy based on the actual ``sys.stdout``
        # state (worker's _TuiWriter if one is installed; fresh
        # self._capture otherwise).
        if self.session.agent_running:
            if cmd_name not in _ALWAYS_ALLOWED_COMMANDS:
                self._run_with_panel_output(lambda: print_error(busy_hint))
                return
            # Escape hatch path (/stop): fall through to normal dispatch.

        all_cmds = get_all_commands(self.session)
        if cmd_name not in all_cmds:

            def _print_unknown() -> None:
                if cmd_name in PROJECT_COMMANDS and not self.session.has_project:
                    print_error("Load a project first: /project <name>")
                else:
                    print_error(
                        f"Unknown command: /{cmd_name}. Type /help for commands."
                    )

            self._run_with_panel_output(_print_unknown)
            return

        handler = all_cmds[cmd_name]["func"]

        # Blocking commands run on a background thread worker. The
        # worker manages its own OutputCapture, session.agent_running
        # lifecycle, and prompt refresh — so we just hand off and return.
        #
        # Defense in depth: reject a second blocking dispatch while
        # one is already live. action_cancel_agent doesn't actually
        # kill the worker thread, so a second worker would race to
        # install a second OutputCapture and crash.
        if cmd_name in _BLOCKING_COMMANDS:
            if self.session.agent_running:
                self._run_with_panel_output(lambda: print_error(busy_hint))
                return
            run_command_in_worker(self, handler, args, cmd_name)
            return

        # Non-blocking inline path. ``_run_with_panel_output`` handles
        # the capture question: if a worker is already running (sys.
        # stdout is _TuiWriter), it runs direct; otherwise it enters
        # self._capture. Safe either way.
        def _run_handler_inline() -> None:
            try:
                handler(self.session, args)
            except SystemExit:
                # A handler calling sys.exit() should close the app
                # rather than propagate and crash the event loop.
                self.session.save_usage()
                self.exit()
            except Exception as exc:
                # Not a silent swallow — the error is printed through
                # whichever capture path is active.
                print_error(f"Error: {exc}")

        self._run_with_panel_output(_run_handler_inline)

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
        """Ctrl+C handler.

        When an agent is running: cooperative cancel — write the
        ``.urika/pause_requested`` flag file that ``PauseController``
        polls between subagents. Do NOT flip ``session.agent_running``
        externally — the worker's ``finally`` block owns that flag,
        and flipping it here would let a second worker spawn while
        the first still holds its ``OutputCapture``, colliding on
        ``sys.stdout``.

        When no agent is running: treat Ctrl+C as a quit request.
        Otherwise users with no visible keybindings get trapped in
        the TUI with Ctrl+C as a silent no-op.
        """
        if not self.session.agent_running:
            # Fall through to quit so Ctrl+C is never a dead key.
            self.action_quit_app()
            return

        panel = self.query_one(OutputPanel)
        # Cooperative stop: write the same pause-flag file /stop uses
        # so experiment runners notice at their next checkpoint.
        if self.session.project_path is not None:
            try:
                flag_dir = self.session.project_path / ".urika"
                flag_dir.mkdir(parents=True, exist_ok=True)
                (flag_dir / "pause_requested").write_text("stop", encoding="utf-8")
            except OSError as exc:
                panel.write_line(f"  \u2717 Cancel-flag write failed: {exc}")
                return
        panel.write_line(
            "  Cancel requested \u2014 agent will stop at next checkpoint."
        )

    def action_quit_app(self) -> None:
        """Quit on Ctrl+D."""
        self.session.save_usage()
        self.exit()
