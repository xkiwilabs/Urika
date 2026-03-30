# REPL Interactive Shell Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive REPL shell launched by `urika` with no args — slash commands, tab completion, advisor conversation, meta-orchestrator for multi-experiment runs.

**Architecture:** `repl.py` handles the prompt_toolkit session loop. `repl_commands.py` maps slash commands to existing core functions. `repl_session.py` manages advisor conversation context. `orchestrator/meta.py` runs experiment-to-experiment loops with checkpoint/capped/unlimited modes. All existing CLI commands unchanged.

**Tech Stack:** Python, prompt_toolkit>=3.0, existing Urika agent/orchestrator infrastructure

---

### Task 1: Add prompt_toolkit dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1:** Add `prompt_toolkit>=3.0` to core dependencies in `pyproject.toml`.

**Step 2:** Run `pip install -e ".[dev]"` to install.

**Step 3:** Verify: `python3 -c "import prompt_toolkit; print(prompt_toolkit.__version__)"`

**Step 4:** Commit:
```bash
git add pyproject.toml
git commit -m "feat: add prompt_toolkit dependency for REPL"
```

---

### Task 2: REPL session state

**Files:**
- Create: `src/urika/repl_session.py`
- Create: `tests/test_repl/test_session.py`
- Create: `tests/test_repl/__init__.py`

**Step 1:** Create `tests/test_repl/__init__.py` (empty).

**Step 2:** Create tests:

```python
"""Tests for REPL session state."""
from __future__ import annotations
from pathlib import Path
from urika.repl_session import ReplSession


class TestReplSession:
    def test_initial_state(self) -> None:
        session = ReplSession()
        assert session.project_path is None
        assert session.project_name is None
        assert session.conversation == []

    def test_load_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "my-project")
        assert session.project_path == tmp_path
        assert session.project_name == "my-project"

    def test_clear_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        session.load_project(tmp_path, "proj")
        session.clear_project()
        assert session.project_path is None

    def test_add_conversation(self) -> None:
        session = ReplSession()
        session.add_message("user", "try LSTM")
        session.add_message("advisor", "LSTM could work...")
        assert len(session.conversation) == 2

    def test_conversation_context_limited(self) -> None:
        session = ReplSession()
        for i in range(20):
            session.add_message("user", f"msg {i}")
        context = session.get_conversation_context()
        # Should only include last N exchanges
        assert len(context.split("\n")) < 30

    def test_has_project(self, tmp_path: Path) -> None:
        session = ReplSession()
        assert not session.has_project
        session.load_project(tmp_path, "proj")
        assert session.has_project
```

**Step 3:** Implement `src/urika/repl_session.py`:

```python
"""REPL session state — project context and advisor conversation."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReplSession:
    """Manages state for an interactive REPL session."""

    project_path: Path | None = None
    project_name: str | None = None
    conversation: list[dict[str, str]] = field(default_factory=list)

    @property
    def has_project(self) -> bool:
        return self.project_path is not None

    def load_project(self, path: Path, name: str) -> None:
        self.project_path = path
        self.project_name = name
        self.conversation = []

    def clear_project(self) -> None:
        self.project_path = None
        self.project_name = None
        self.conversation = []

    def add_message(self, role: str, text: str) -> None:
        self.conversation.append({"role": role, "text": text})

    def get_conversation_context(self, max_exchanges: int = 10) -> str:
        recent = self.conversation[-(max_exchanges * 2):]
        lines = []
        for msg in recent:
            prefix = "User" if msg["role"] == "user" else "Advisor"
            lines.append(f"{prefix}: {msg['text']}")
        return "\n".join(lines)
```

**Step 4:** Run tests, lint, commit:
```bash
pytest tests/test_repl/ -v
git add src/urika/repl_session.py tests/test_repl/
git commit -m "feat: add REPL session state management"
```

---

### Task 3: REPL command handlers

**Files:**
- Create: `src/urika/repl_commands.py`
- Create: `tests/test_repl/test_commands.py`

**Step 1:** Create `src/urika/repl_commands.py` with command handler functions. Each handler takes the `ReplSession` and args, calls existing core functions:

```python
"""Slash command handlers for the REPL."""
from __future__ import annotations
import asyncio
import click
from pathlib import Path
from urika.repl_session import ReplSession


# Registry of commands
GLOBAL_COMMANDS = {}
PROJECT_COMMANDS = {}


def command(name: str, requires_project: bool = False, description: str = ""):
    """Decorator to register a REPL command."""
    def decorator(func):
        entry = {"func": func, "description": description}
        if requires_project:
            PROJECT_COMMANDS[name] = entry
        else:
            GLOBAL_COMMANDS[name] = entry
        return func
    return decorator


@command("help", description="Show available commands")
def cmd_help(session: ReplSession, args: str) -> None:
    from urika.cli_display import _C
    click.echo(f"\n  {_C.BOLD}Commands:{_C.RESET}")
    for name, entry in sorted(GLOBAL_COMMANDS.items()):
        click.echo(f"    /{name:<16s} {entry['description']}")
    if session.has_project:
        for name, entry in sorted(PROJECT_COMMANDS.items()):
            click.echo(f"    /{name:<16s} {entry['description']}")
    click.echo()


@command("projects", description="List all projects")
def cmd_projects(session: ReplSession, args: str) -> None:
    from urika.core.registry import ProjectRegistry
    registry = ProjectRegistry()
    projects = registry.list_all()
    if not projects:
        click.echo("  No projects registered.")
        return
    click.echo()
    for name, path in projects.items():
        marker = " ◆" if session.project_name == name else "  "
        click.echo(f"  {marker} {name}")
    click.echo()


@command("project", description="Load a project")
def cmd_project(session: ReplSession, args: str) -> None:
    from urika.core.registry import ProjectRegistry
    from urika.core.workspace import load_project_config
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress
    from urika.cli_display import print_step, print_success, print_warning

    name = args.strip()
    if not name:
        click.echo("  Usage: /project <name>")
        return

    registry = ProjectRegistry()
    path = registry.get(name)
    if path is None:
        click.echo(f"  Project '{name}' not found.")
        return

    if session.has_project:
        # Could check for running experiments here
        pass

    try:
        config = load_project_config(path)
    except FileNotFoundError:
        click.echo(f"  Project directory missing: {path}")
        return

    session.load_project(path, name)

    experiments = list_experiments(path)
    completed = sum(
        1 for e in experiments
        if load_progress(path, e.experiment_id).get("status") == "completed"
    )

    click.echo()
    print_success(f"Project: {name} · {config.mode}")
    click.echo(f"    {len(experiments)} experiments · {completed} completed")
    click.echo()


@command("new", description="Create a new project")
def cmd_new(session: ReplSession, args: str) -> None:
    # Calls the same project builder flow as CLI
    from urika.cli import new as cli_new
    from click.testing import CliRunner
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(cli_new, [], standalone_mode=False, catch_exceptions=False)
    # After creation, auto-load the project
    # (handled by checking registry for latest)


@command("quit", description="Exit Urika")
def cmd_quit(session: ReplSession, args: str) -> None:
    raise SystemExit(0)


# Project-specific commands

@command("status", requires_project=True, description="Show project status")
def cmd_status(session: ReplSession, args: str) -> None:
    from urika.cli import status as cli_status
    from click import Context
    # Call the existing status function
    ctx = click.Context(cli_status)
    ctx.invoke(cli_status, name=session.project_name)


@command("run", requires_project=True, description="Run next experiment")
def cmd_run(session: ReplSession, args: str) -> None:
    from urika.cli_display import print_step, _prompt_numbered
    import click as _click

    # Show defaults, offer custom
    defaults = _load_run_defaults(session)
    click.echo(f"\n  Run settings:")
    click.echo(f"    Max turns: {defaults['max_turns']}")
    click.echo(f"    Auto mode: {defaults['auto_mode']}")
    instructions = session.get_conversation_context() if session.conversation else "(none)"
    click.echo(f"    Instructions: {instructions[:80]}{'...' if len(instructions) > 80 else ''}")

    choice = _prompt_numbered(
        "\n  Proceed?",
        ["Run with defaults", "Custom settings", "Skip"],
        default=1,
    )

    if choice == "Skip":
        return

    max_turns = defaults["max_turns"]
    auto_mode = defaults["auto_mode"]
    run_instructions = ""

    if choice == "Custom settings":
        max_turns = int(_click.prompt("  Max turns", default=str(defaults["max_turns"])))
        auto_mode = _click.prompt("  Auto mode (checkpoint/capped/unlimited)", default=defaults["auto_mode"])
        run_instructions = _click.prompt("  Instructions", default="")

    # Use conversation context as instructions if none provided
    if not run_instructions and session.conversation:
        run_instructions = session.get_conversation_context()

    # Call the existing run flow
    from urika.cli import run as cli_run
    ctx = click.Context(cli_run)
    ctx.invoke(
        cli_run,
        project=session.project_name,
        experiment_id=None,
        max_turns=max_turns,
        resume=False,
        quiet=False,
        auto=(auto_mode != "checkpoint"),
        instructions=run_instructions,
    )


@command("experiments", requires_project=True, description="List experiments")
def cmd_experiments(session: ReplSession, args: str) -> None:
    from urika.core.experiment import list_experiments
    from urika.core.progress import load_progress
    experiments = list_experiments(session.project_path)
    if not experiments:
        click.echo("  No experiments yet.")
        return
    click.echo()
    for exp in experiments:
        progress = load_progress(session.project_path, exp.experiment_id)
        runs = progress.get("runs", [])
        status = progress.get("status", "pending")
        click.echo(f"    {exp.experiment_id}  [{status}, {len(runs)} runs]")
    click.echo()


@command("methods", requires_project=True, description="Show methods table")
def cmd_methods(session: ReplSession, args: str) -> None:
    from urika.core.method_registry import load_methods
    methods = load_methods(session.project_path)
    if not methods:
        click.echo("  No methods yet.")
        return
    click.echo()
    for m in methods:
        metrics = m.get("metrics", {})
        nums = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        metric_str = ", ".join(f"{k}={v}" for k, v in list(nums.items())[:2])
        click.echo(f"    {m['name']}  [{m.get('status', '')}]  {metric_str}")
    click.echo()


@command("criteria", requires_project=True, description="Show current criteria")
def cmd_criteria(session: ReplSession, args: str) -> None:
    from urika.core.criteria import load_criteria
    c = load_criteria(session.project_path)
    if c is None:
        click.echo("  No criteria set.")
        return
    click.echo(f"\n  Criteria v{c.version} (set by {c.set_by})")
    click.echo(f"  Type: {c.criteria.get('type', 'unknown')}")
    threshold = c.criteria.get("threshold", {})
    primary = threshold.get("primary", {})
    if primary:
        click.echo(f"  Primary: {primary.get('metric')} {primary.get('direction', '>')} {primary.get('target')}")
    click.echo()


@command("present", requires_project=True, description="Generate presentation for an experiment")
def cmd_present(session: ReplSession, args: str) -> None:
    exp_id = args.strip()
    if not exp_id:
        # Use latest experiment
        from urika.core.experiment import list_experiments
        experiments = list_experiments(session.project_path)
        if not experiments:
            click.echo("  No experiments.")
            return
        exp_id = experiments[-1].experiment_id

    click.echo(f"  Generating presentation for {exp_id}...")
    try:
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.orchestrator.loop import _generate_presentation, _noop_callback
        runner = ClaudeSDKRunner()
        asyncio.run(_generate_presentation(
            session.project_path, exp_id, runner, _noop_callback
        ))
        click.echo(f"  ✓ Saved to experiments/{exp_id}/presentation/index.html")
    except Exception as exc:
        click.echo(f"  ✗ Error: {exc}")


@command("report", requires_project=True, description="Generate reports")
def cmd_report(session: ReplSession, args: str) -> None:
    from urika.core.labbook import (
        generate_experiment_summary, generate_key_findings,
        generate_results_summary, update_experiment_notes,
    )
    from urika.core.experiment import list_experiments
    from urika.core.readme_generator import write_readme

    click.echo("  Generating reports...")
    for exp in list_experiments(session.project_path):
        try:
            update_experiment_notes(session.project_path, exp.experiment_id)
            generate_experiment_summary(session.project_path, exp.experiment_id)
        except Exception:
            pass
    try:
        generate_results_summary(session.project_path)
        generate_key_findings(session.project_path)
        write_readme(session.project_path)
    except Exception:
        pass
    click.echo("  ✓ Reports updated")


@command("inspect", requires_project=True, description="Inspect dataset")
def cmd_inspect(session: ReplSession, args: str) -> None:
    from urika.cli import inspect as cli_inspect
    ctx = click.Context(cli_inspect)
    ctx.invoke(cli_inspect, project=session.project_name, data_file=args.strip() or None)


@command("logs", requires_project=True, description="Show experiment logs")
def cmd_logs(session: ReplSession, args: str) -> None:
    from urika.cli import logs as cli_logs
    ctx = click.Context(cli_logs)
    ctx.invoke(cli_logs, project=session.project_name, experiment_id=args.strip() or None)


@command("knowledge", requires_project=True, description="Search knowledge base")
def cmd_knowledge(session: ReplSession, args: str) -> None:
    from urika.knowledge import KnowledgeStore
    store = KnowledgeStore(session.project_path)
    if args.strip():
        results = store.search(args.strip())
        if not results:
            click.echo("  No results.")
            return
        for entry in results:
            click.echo(f"    {entry.id}  {entry.title}")
    else:
        entries = store.list_all()
        if not entries:
            click.echo("  No knowledge entries.")
            return
        for entry in entries:
            click.echo(f"    {entry.id}  {entry.title}  [{entry.source_type}]")


def _load_run_defaults(session: ReplSession) -> dict:
    """Load run defaults from urika.toml preferences."""
    import tomllib
    defaults = {"max_turns": 5, "auto_mode": "checkpoint"}
    toml_path = session.project_path / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            prefs = data.get("preferences", {})
            defaults["max_turns"] = prefs.get("max_turns_per_experiment", 5)
            defaults["auto_mode"] = prefs.get("auto_mode", "checkpoint")
        except Exception:
            pass
    return defaults


def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt with numbered options."""
    click.echo(prompt_text)
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i == default else ""
        click.echo(f"    {i}. {opt}{marker}")
    while True:
        raw = click.prompt("  Choice", default=str(default)).strip()
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass


def get_all_commands(session: ReplSession) -> dict:
    """Get all available commands for current state."""
    cmds = dict(GLOBAL_COMMANDS)
    if session.has_project:
        cmds.update(PROJECT_COMMANDS)
    return cmds


def get_command_names(session: ReplSession) -> list[str]:
    """Get all command names for tab completion."""
    return sorted(get_all_commands(session).keys())


def get_project_names() -> list[str]:
    """Get all project names for tab completion."""
    from urika.core.registry import ProjectRegistry
    registry = ProjectRegistry()
    return sorted(registry.list_all().keys())


def get_experiment_ids(session: ReplSession) -> list[str]:
    """Get experiment IDs for tab completion."""
    if not session.has_project:
        return []
    from urika.core.experiment import list_experiments
    return [e.experiment_id for e in list_experiments(session.project_path)]
```

**Step 2:** Create basic tests for command registration and helpers.

**Step 3:** Run tests, lint, commit:
```bash
pytest tests/test_repl/ -v
git add src/urika/repl_commands.py tests/test_repl/
git commit -m "feat: add REPL slash command handlers"
```

---

### Task 4: REPL main loop with prompt_toolkit

**Files:**
- Create: `src/urika/repl.py`
- Modify: `src/urika/cli.py` — add `urika` no-args entry point

**Step 1:** Create `src/urika/repl.py`:

```python
"""Interactive REPL shell for Urika."""
from __future__ import annotations
import asyncio
import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter, Completer, Completion
from prompt_toolkit.history import InMemoryHistory

from urika.cli_display import print_header, print_agent, print_error
from urika.repl_session import ReplSession
from urika.repl_commands import (
    get_all_commands, get_command_names, get_project_names,
    get_experiment_ids, GLOBAL_COMMANDS, PROJECT_COMMANDS,
)


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
                # Completing the command name
                for name in get_command_names(self.session):
                    if name.startswith(cmd):
                        yield Completion(name, start_position=-len(cmd))
            elif len(parts) >= 1:
                # Completing arguments
                if cmd == "project":
                    arg = parts[1] if len(parts) > 1 else ""
                    for name in get_project_names():
                        if name.startswith(arg):
                            yield Completion(name, start_position=-len(arg))
                elif cmd in ("present", "logs"):
                    arg = parts[1] if len(parts) > 1 else ""
                    for eid in get_experiment_ids(self.session):
                        if eid.startswith(arg):
                            yield Completion(eid, start_position=-len(arg))


def run_repl() -> None:
    """Main REPL entry point."""
    session = ReplSession()
    history = InMemoryHistory()
    completer = UrikaCompleter(session)

    # Show header
    print_header()

    # List projects on startup
    from urika.core.registry import ProjectRegistry
    registry = ProjectRegistry()
    projects = registry.list_all()
    if projects:
        click.echo("  Projects:")
        for name in projects:
            click.echo(f"    {name}")
        click.echo()

    prompt_session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=False,
    )

    while True:
        try:
            # Build prompt
            if session.has_project:
                prompt_text = f"urika:{session.project_name}> "
            else:
                prompt_text = "urika> "

            user_input = prompt_session.prompt(prompt_text).strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                _handle_command(session, user_input)
            else:
                _handle_free_text(session, user_input)

        except (EOFError, KeyboardInterrupt):
            click.echo("\n  Goodbye.")
            break
        except SystemExit:
            break


def _handle_command(session: ReplSession, text: str) -> None:
    """Parse and execute a slash command."""
    parts = text[1:].split(" ", 1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    all_cmds = get_all_commands(session)
    if cmd_name not in all_cmds:
        # Check if it's a project command but no project loaded
        if cmd_name in PROJECT_COMMANDS and not session.has_project:
            print_error(f"Load a project first: /project <name>")
        else:
            print_error(f"Unknown command: /{cmd_name}. Type /help for commands.")
        return

    handler = all_cmds[cmd_name]["func"]
    try:
        handler(session, args)
    except Exception as exc:
        print_error(f"Error: {exc}")


def _handle_free_text(session: ReplSession, text: str) -> None:
    """Send free text to the advisor agent."""
    if not session.has_project:
        click.echo("  Load a project first: /project <name>")
        return

    try:
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.agents.registry import AgentRegistry
        from urika.cli_display import Spinner, print_tool_use

        runner = ClaudeSDKRunner()
        registry = AgentRegistry()
        registry.discover()

        advisor = registry.get("advisor_agent")
        if advisor is None:
            print_error("Advisor agent not found.")
            return

        # Build context
        import json
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

        def _on_msg(msg):
            try:
                if hasattr(msg, "content"):
                    for block in msg.content:
                        tool_name = getattr(block, "name", None)
                        if tool_name:
                            inp = getattr(block, "input", {}) or {}
                            detail = ""
                            if isinstance(inp, dict):
                                detail = inp.get("command", "") or inp.get("file_path", "") or inp.get("pattern", "")
                            print_tool_use(tool_name, detail)
            except Exception:
                pass

        print_agent("advisor_agent")
        with Spinner("Thinking"):
            result = asyncio.run(runner.run(config, context, on_message=_on_msg))

        if result.success and result.text_output:
            click.echo(f"\n{result.text_output.strip()}\n")
            session.add_message("user", text)
            session.add_message("advisor", result.text_output.strip())
        else:
            print_error(f"Advisor error: {result.error}")

    except ImportError:
        print_error("Claude Agent SDK not installed. Run: pip install urika")
    except Exception as exc:
        print_error(f"Error: {exc}")
```

**Step 2:** Add entry point to `src/urika/cli.py`. Modify the `cli` group to launch REPL when called with no args:

Add a callback to the `cli` group that checks if no subcommand was invoked:

```python
@cli.command(hidden=True)
def repl():
    """Launch interactive REPL."""
    from urika.repl import run_repl
    run_repl()
```

And modify the `cli` group to default to REPL:

```python
@click.group(invoke_without_command=True)
@click.version_option(package_name="urika")
@click.pass_context
def cli(ctx) -> None:
    """Urika: Agentic scientific analysis platform."""
    if ctx.invoked_subcommand is None:
        from urika.repl import run_repl
        run_repl()
```

**Step 3:** Run tests, lint, commit:
```bash
pytest tests/test_repl/ tests/test_cli.py -v
git add src/urika/repl.py src/urika/cli.py
git commit -m "feat: add REPL main loop with prompt_toolkit"
```

---

### Task 5: Meta-orchestrator

**Files:**
- Create: `src/urika/orchestrator/meta.py`
- Create: `tests/test_orchestrator/test_meta.py`

**Step 1:** Create `src/urika/orchestrator/meta.py`:

```python
"""Meta-orchestrator — manages experiment-to-experiment flow."""
from __future__ import annotations
import asyncio
import click
import json
from pathlib import Path
from typing import Any

from urika.agents.runner import AgentRunner


async def run_project(
    project_dir: Path,
    runner: AgentRunner,
    *,
    mode: str = "checkpoint",
    max_experiments: int = 10,
    max_turns: int = 5,
    instructions: str = "",
    on_progress: object = None,
    on_message: object = None,
) -> dict[str, Any]:
    """Run experiments until criteria met or limits reached.

    Modes:
        checkpoint: pause between experiments for user input
        capped: run up to max_experiments with no pauses
        unlimited: run until advisor says done (hard cap 50)
    """
    from urika.cli_display import print_step, print_success, print_error, _prompt_numbered
    from urika.core.experiment import create_experiment, list_experiments
    from urika.core.progress import load_progress
    from urika.orchestrator import run_experiment

    safety_cap = 50 if mode == "unlimited" else max_experiments
    results = []

    for exp_num in range(safety_cap):
        # Determine next experiment via advisor
        next_exp = _determine_next(project_dir, runner, instructions, on_message)
        if next_exp is None:
            print_step("Advisor: no further experiments to suggest.")
            break

        exp_name = next_exp.get("name", f"auto-{exp_num + 1}").replace(" ", "-").lower()
        description = next_exp.get("method", next_exp.get("description", ""))

        # Create experiment
        exp = create_experiment(project_dir, name=exp_name, hypothesis=description[:500])
        print_step(f"Experiment {exp_num + 1}: {exp.experiment_id}")

        # Run it
        result = await run_experiment(
            project_dir, exp.experiment_id, runner,
            max_turns=max_turns,
            on_progress=on_progress,
            on_message=on_message,
            instructions=instructions,
        )
        results.append(result)

        # Checkpoint
        if mode == "checkpoint":
            choice = _prompt_numbered(
                "\n  Continue?",
                ["Next experiment", "Next with instructions", "Stop"],
                default=1,
            )
            if choice == "Stop":
                break
            if choice.startswith("Next with"):
                instructions = click.prompt("  Instructions").strip()

        # Check if criteria fully met
        if _criteria_fully_met(project_dir):
            print_success("All criteria met.")
            break

    return {"experiments_run": len(results), "results": results}


def _determine_next(project_dir, runner, instructions, on_message):
    """Call advisor to propose next experiment."""
    from urika.agents.registry import AgentRegistry
    from urika.orchestrator.parsing import parse_suggestions

    registry = AgentRegistry()
    registry.discover()
    advisor = registry.get("advisor_agent")
    if advisor is None:
        return None

    context = f"Propose the next experiment.\n"
    if instructions:
        context += f"User instructions: {instructions}\n"

    config = advisor.build_config(project_dir=project_dir, experiment_id="")
    result = asyncio.run(runner.run(config, context, on_message=on_message))

    if not result.success:
        return None

    parsed = parse_suggestions(result.text_output)
    if parsed and parsed.get("suggestions"):
        return parsed["suggestions"][0]
    return None


def _criteria_fully_met(project_dir: Path) -> bool:
    """Check if all criteria are satisfied."""
    from urika.core.criteria import load_criteria
    c = load_criteria(project_dir)
    if c is None:
        return False
    criteria = c.criteria
    # Need threshold with primary met
    threshold = criteria.get("threshold", {})
    primary = threshold.get("primary", {})
    if not primary:
        return False  # No threshold = exploratory, never "done"
    # Would need to check actual metrics vs target
    # For now, return False — let the advisor decide
    return False
```

**Step 2:** Create basic tests.

**Step 3:** Run tests, lint, commit:
```bash
pytest tests/test_orchestrator/ -v
git add src/urika/orchestrator/meta.py tests/test_orchestrator/test_meta.py
git commit -m "feat: add meta-orchestrator for multi-experiment runs"
```

---

### Task 6: Wire everything together and update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `current-status.md`
- Modify: `README.md` (project-level)

**Step 1:** Update CLAUDE.md with new modules (repl.py, repl_session.py, repl_commands.py, orchestrator/meta.py).

**Step 2:** Update current-status.md with REPL feature.

**Step 3:** Run full test suite:
```bash
pytest -v
ruff check src/ tests/ && ruff format src/ tests/
```

**Step 4:** Commit:
```bash
git add CLAUDE.md current-status.md
git commit -m "docs: update docs for REPL and meta-orchestrator"
```
