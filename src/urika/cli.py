"""Urika CLI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from urika.core.experiment import create_experiment, list_experiments
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.workspace import load_project_config
from urika.evaluation.leaderboard import load_leaderboard
from urika.tools import ToolRegistry


def _make_on_message() -> object:
    """Create an on_message callback that prints tool use events."""
    from urika.cli_display import print_tool_use

    def _on_msg(msg: object) -> None:
        try:
            if hasattr(msg, "content"):
                for block in msg.content:
                    tool_name = getattr(block, "name", None)
                    if tool_name:
                        inp = getattr(block, "input", {}) or {}
                        detail = ""
                        if isinstance(inp, dict):
                            detail = (
                                inp.get("command", "")
                                or inp.get("file_path", "")
                                or inp.get("pattern", "")
                            )
                        print_tool_use(tool_name, detail)
        except Exception:
            pass

    return _on_msg


def _record_agent_usage(
    project_path: Path,
    result: object,
    start_iso: str,
    start_ms: int,
) -> None:
    """Record usage from a single agent call in the CLI."""
    import time

    from datetime import datetime, timezone

    try:
        from urika.core.usage import record_session

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        record_session(
            project_path,
            started=start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=elapsed_ms,
            tokens_in=getattr(result, "tokens_in", 0),
            tokens_out=getattr(result, "tokens_out", 0),
            cost_usd=getattr(result, "cost_usd", 0.0) or 0.0,
            agent_calls=1,
            experiments_run=0,
        )
    except Exception:
        pass


def _projects_dir() -> Path:
    """Default directory for new projects."""
    env = os.environ.get("URIKA_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path.home() / "urika-projects"


def _resolve_project(name: str) -> tuple[Path, ProjectConfig]:
    """Look up project by name. Raises ClickException on error."""
    registry = ProjectRegistry()
    project_path = registry.get(name)
    if project_path is None:
        raise click.ClickException(f"Project '{name}' not found in registry.")
    try:
        config = load_project_config(project_path)
    except FileNotFoundError:
        raise click.ClickException(f"Project directory missing at {project_path}")
    return project_path, config


def _ensure_project(project: str | None) -> str:
    """If project is None, prompt user to pick from registered projects."""
    if project:
        return project
    registry = ProjectRegistry()
    projects = registry.list_all()
    if not projects:
        raise click.ClickException("No projects registered. Create one with: urika new")
    names = list(projects.keys())
    if len(names) == 1:
        return names[0]
    from urika.cli_helpers import UserCancelled, interactive_numbered

    try:
        return interactive_numbered("\n  Select project:", names, default=1)
    except UserCancelled:
        raise SystemExit(0)


class _UrikaCLI(click.Group):
    """Custom CLI group that catches UserCancelled globally."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except SystemExit:
            raise  # Let clean exits through
        except Exception as exc:
            # Catch UserCancelled from any command — exit cleanly
            if type(exc).__name__ == "UserCancelled":
                raise SystemExit(0)
            raise


@click.group(cls=_UrikaCLI, invoke_without_command=True)
@click.version_option(package_name="urika")
@click.pass_context
def cli(ctx) -> None:
    """Urika: Agentic scientific analysis platform."""
    # Load credentials from ~/.urika/secrets.env
    from urika.core.secrets import load_secrets

    load_secrets()

    # Check for updates on every CLI invocation (cached, non-blocking)
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates()
        if update_info:
            from urika.cli_display import _C

            msg = format_update_message(update_info)
            click.echo(f"{_C.DIM}  ↑ {msg}{_C.RESET}")
    except Exception:
        pass

    if ctx.invoked_subcommand is None:
        from urika.repl import run_repl

        run_repl()


def _test_endpoint(url: str) -> bool:
    """Test if an API endpoint is reachable (3s timeout)."""
    import urllib.request
    import urllib.error

    # Try common health/version endpoints
    for path in ["", "/api/tags", "/v1/models"]:
        try:
            test_url = url.rstrip("/") + path
            req = urllib.request.Request(
                test_url,
                headers={"User-Agent": "urika-endpoint-check"},
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            continue
    return False


def _prompt_numbered(prompt_text: str, options: list[str], default: int = 1) -> str:
    """Prompt user with numbered options. Returns the selected option text.

    Exits cleanly (SystemExit 0) if the user cancels.
    """
    from urika.cli_helpers import UserCancelled, interactive_numbered

    try:
        return interactive_numbered(prompt_text, options, default=default)
    except UserCancelled:
        raise SystemExit(0)


def _prompt_path(prompt_text: str, must_exist: bool = True) -> str | None:
    """Prompt for a path, re-asking if it doesn't exist. Empty = skip."""
    from urika.cli_helpers import interactive_prompt

    while True:
        try:
            raw = interactive_prompt(prompt_text).strip()
        except click.Abort:
            return None
        if not raw:
            return None
        resolved = Path(raw).resolve()
        if not must_exist or resolved.exists():
            return str(resolved)
        click.echo(f"  Path not found: {raw}")
        click.echo("  Please check the path and try again.")


@cli.command()
@click.argument("name", required=False, default=None)
@click.option("-q", "--question", default=None, help="Research question.")
@click.option(
    "-m",
    "--mode",
    default=None,
    type=click.Choice(["exploratory", "confirmatory", "pipeline"]),
    help="Investigation mode.",
)
@click.option(
    "--data", "data_path", default=None, help="Path to data file or directory."
)
@click.option("--description", default=None, help="Project description.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def new(
    name: str | None,
    question: str | None,
    mode: str | None,
    data_path: str | None,
    description: str | None,
    json_output: bool = False,
) -> None:
    """Create a new project."""
    from urika.cli_display import (
        Spinner,
        print_agent,
        print_error,
        print_header,
        print_step,
        print_success,
    )
    from urika.core.project_builder import ProjectBuilder

    # JSON mode requires all essential flags — refuse to go interactive
    if json_output:
        missing = []
        if name is None:
            missing.append("NAME argument")
        if question is None:
            missing.append("--question / -q")
        if mode is None:
            missing.append("--mode / -m")
        if missing:
            from urika.cli_helpers import output_json_error

            output_json_error(
                f"Missing required flags for --json mode: {', '.join(missing)}"
            )
            raise SystemExit(1)

    # Show welcome header immediately (skip if called from REPL)
    if not json_output and not os.environ.get("URIKA_REPL"):
        print_header()

    # Prompt for missing required fields
    from urika.cli_helpers import interactive_prompt, interactive_confirm

    if name is None:
        name = interactive_prompt("Project name", required=True)

    # Load saved defaults from ~/.urika/settings.toml
    from urika.core.settings import get_default_privacy

    _saved_privacy = get_default_privacy()
    _saved_mode = _saved_privacy.get("mode", "open")
    _saved_endpoints = _saved_privacy.get("endpoints", {})
    _saved_private_ep = _saved_endpoints.get("private", {})
    _saved_url = _saved_private_ep.get("base_url", "")
    _saved_key_env = _saved_private_ep.get("api_key_env", "")

    # In JSON mode, skip all interactive prompts — use saved defaults
    if json_output:
        privacy_mode_val = _saved_mode
        private_endpoint_url = _saved_url
        private_endpoint_key_env = _saved_key_env
        if data_path is not None:
            data_path = data_path.strip()
            resolved = Path(data_path).resolve()
            data_path = str(resolved) if resolved.exists() else None
        if description is None:
            description = ""
        web_search = False
        use_venv = False
    else:
        # Privacy mode — ask FIRST, before data path
        _mode_default = {"open": 1, "private": 2, "hybrid": 3}.get(_saved_mode, 1)
        _has_saved = _saved_mode != "open"
        _saved_hint = f" (saved default: {_saved_mode})" if _has_saved else ""
        privacy_choice = _prompt_numbered(
            f"\nData privacy mode:{_saved_hint}",
            [
                "Open — agents use cloud models, no restrictions",
                "Private — all agents use private/local endpoints only",
                "Hybrid — data reading is private, thinking uses cloud models",
            ],
            default=_mode_default,
        )
        _privacy_map = {"Open": "open", "Private": "private", "Hybrid": "hybrid"}
        privacy_mode_val = _privacy_map.get(
            privacy_choice.split(" —")[0].strip(), "open"
        )

        private_endpoint_url = ""
        private_endpoint_key_env = ""
        if privacy_mode_val in ("private", "hybrid"):
            _url_default = _saved_url or "http://localhost:11434"
            _key_default = _saved_key_env or ""
            if _saved_url:
                click.echo(f"\n  Using saved endpoint: {_saved_url}")
                click.echo("  Press Enter to keep, or type a new URL.")
            else:
                click.echo(
                    "\n  Configure the private endpoint.\n"
                    "  This can be a local Ollama instance or "
                    "a secure institutional server."
                )
            while True:
                private_endpoint_url = interactive_prompt(
                    "Private endpoint URL",
                    default=_url_default,
                )
                private_endpoint_key_env = interactive_prompt(
                    "API key env var (empty for Ollama)",
                    default=_key_default,
                )
                # Validate the endpoint is reachable
                print_step("Testing endpoint connection…")
                if _test_endpoint(private_endpoint_url):
                    print_success(f"Connected to {private_endpoint_url}")
                    break
                else:
                    print_error(f"Could not connect to {private_endpoint_url}")
                    retry = click.prompt(
                        "  Try again, switch to open mode, or quit?",
                        type=click.Choice(["retry", "open", "quit"]),
                        default="retry",
                    )
                    if retry == "open":
                        privacy_mode_val = "open"
                        private_endpoint_url = ""
                        private_endpoint_key_env = ""
                        print_step("Switched to open mode.")
                        break
                    elif retry == "quit":
                        raise click.Abort()
                    # retry loops back

        # Validate data path — keep asking until valid or skipped
        if data_path is not None:
            data_path = data_path.strip()
            resolved = Path(data_path).resolve()
            if not resolved.exists():
                click.echo(f"  Path not found: {data_path}")
                data_path = _prompt_path("Path to data (file or directory)")
            else:
                data_path = str(resolved)
        else:
            data_path = _prompt_path("Path to data (file or directory)")

        if description is None:
            description = interactive_prompt(
                "Describe the project — what are you trying to analyze or predict",
                default="",
            )
        if question is None:
            question = interactive_prompt("Research question", required=True)
        if mode is None:
            mode = _prompt_numbered(
                "Investigation mode:",
                ["exploratory", "confirmatory", "pipeline"],
                default=1,
            )

        if privacy_mode_val == "private":
            web_search = False
        else:
            web_search = interactive_confirm(
                "Allow agents to search the web for relevant papers?",
                default=False,
            )

        click.echo(
            "\n  Isolated environments prevent package conflicts between projects.\n"
            "  Use one if agents will pip install large packages (e.g., torch,\n"
            "  mne, transformers) or if you run multiple projects with different\n"
            "  library versions."
        )
        use_venv = interactive_confirm(
            "Create isolated environment for this project?",
            default=False,
        )

    source = Path(data_path) if data_path else None
    builder = ProjectBuilder(
        name=name,
        source_path=source,
        projects_dir=_projects_dir(),
        description=description or "",
        question=question,
        mode=mode,
    )

    # Check if project already exists before doing work
    project_dir = _projects_dir() / name
    if json_output:
        # In JSON mode, overwrite silently if exists
        if (project_dir / "urika.toml").exists():
            import shutil

            shutil.rmtree(project_dir)
    else:
        while (project_dir / "urika.toml").exists():
            choice = _prompt_numbered(
                f"Project '{name}' already exists:",
                ["Overwrite", "New name", "Abort"],
                default=1,
            )
            if choice == "Abort":
                raise click.ClickException("Aborted.")
            if choice == "Overwrite":
                import shutil

                shutil.rmtree(project_dir)
                break
            # New name
            name = interactive_prompt("New project name", required=True)
            builder.name = name
            project_dir = _projects_dir() / name

    # Show project details header (skip if called from REPL or JSON mode)
    if not json_output and not os.environ.get("URIKA_REPL"):
        print_header(
            project_name=name,
            mode=mode,
            data_source=data_path or "",
        )

    # --- Set builder settings from earlier prompts ---
    builder.privacy_mode = privacy_mode_val
    builder.private_endpoint_url = private_endpoint_url
    builder.private_endpoint_key_env = private_endpoint_key_env
    builder.web_search = web_search
    builder.use_venv = use_venv

    # JSON mode: fast path — just write project and return
    if json_output:
        project_dir = builder.write_project()
        registry = ProjectRegistry()
        registry.register(name, project_dir)
        from urika.cli_helpers import output_json

        output_json({"project": name, "path": str(project_dir)})
        return

    # Scan and profile if a data path was provided
    scan_result = None
    data_summary = None
    extra_profiles: dict | None = None
    has_knowledge = False
    if data_path:
        with Spinner("Scanning data source"):
            scan_result = builder.scan()
        click.echo(scan_result.summary())

        has_knowledge = bool(scan_result.docs or scan_result.papers or scan_result.code)

        with Spinner("Profiling data files"):
            try:
                data_summary = builder.profile_data()
                print_success(
                    f"Data profile: {data_summary.n_rows} rows,"
                    f" {data_summary.n_columns} columns"
                )
            except (ValueError, Exception):
                pass

        # Profile non-tabular data types
        extra_profiles = builder.profile_all_data()
        if extra_profiles:
            for dtype, profile in extra_profiles.items():
                count = profile.get("count", 0)
                formats = ", ".join(profile.get("formats", []))
                print_success(f"{dtype.title()}: {count} files ({formats})")

    # Write project files first so knowledge can be ingested
    with Spinner("Writing project files"):
        project_dir = builder.write_project()

    # Ingest knowledge BEFORE agent Q&A — agents benefit from domain context
    if data_path and scan_result and has_knowledge:
        n_docs = len(scan_result.docs)
        n_papers = len(scan_result.papers)
        click.echo(
            f"\n  Found {n_docs} documentation file(s) and {n_papers} paper(s)"
            " in the data path."
        )
        ingest = interactive_confirm(
            "Ingest into the knowledge base?",
            default=True,
        )
        if ingest:
            with Spinner("Ingesting knowledge"):
                _ingest_knowledge(project_dir, scan_result)

    # Always offer to add more knowledge — even if some was found
    if data_path and scan_result:
        has_readme = has_knowledge and any(
            d.name.lower() in ("readme.md", "readme.txt", "readme")
            for d in scan_result.docs
        )
        n_papers = len(scan_result.papers) if scan_result else 0

        tips = []
        if not has_readme:
            tips.append("a description of the data collection methods and procedures")
        if n_papers == 0:
            tips.append("1-2 relevant research papers from your domain")

        if tips:
            click.echo(
                "\n  Adding knowledge improves analysis quality. Consider adding:"
            )
            for tip in tips:
                click.echo(f"    - {tip}")

        extra_path = _prompt_path(
            "\n  Path to additional knowledge to ingest (paper, doc, or folder)"
            " — press Enter to skip"
        )
        if extra_path:
            from urika.knowledge import KnowledgeStore

            store = KnowledgeStore(project_dir)
            extra = Path(extra_path)
            if extra.is_dir():
                ingested = 0
                for f in sorted(extra.rglob("*")):
                    if f.is_file() and f.suffix.lower() in (
                        ".pdf",
                        ".md",
                        ".txt",
                        ".rst",
                        ".html",
                    ):
                        try:
                            store.ingest(str(f))
                            ingested += 1
                        except Exception:
                            pass
                if ingested:
                    print_success(f"Ingested {ingested} file(s)")
            else:
                try:
                    entry = store.ingest(str(extra))
                    print_success(
                        f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})'
                    )
                except Exception as exc:
                    print_error(f"Could not ingest: {exc}")
    elif not data_path:
        pass  # No data path — skip knowledge entirely
    else:
        click.echo("\n  No documentation or papers found in the data path.")
        extra_path = _prompt_path(
            "  Path to knowledge to ingest (paper, doc, or folder)"
            " — press Enter to skip"
        )
        if extra_path:
            from urika.knowledge import KnowledgeStore

            store = KnowledgeStore(project_dir)
            try:
                entry = store.ingest(str(extra_path))
                print_success(
                    f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})'
                )
            except Exception as exc:
                print_error(f"Could not ingest: {exc}")

    # --- Interactive agent loop (after knowledge is available) ---
    print_agent("project_builder")
    try:
        _run_builder_agent_loop(
            builder,
            scan_result,
            data_summary,
            description or "",
            question,
            extra_profiles=extra_profiles if data_path else None,
        )
    except Exception as exc:
        print_error(f"Agent loop unavailable ({exc}). Continuing with manual setup.")

    registry = ProjectRegistry()
    registry.register(name, project_dir)

    print_success(f"Created project '{name}' at {project_dir}")

    # Offer to run the first planned experiment
    import json

    suggestions_path = project_dir / "suggestions" / "initial.json"
    first_name = ""
    first_desc = ""
    if suggestions_path.exists():
        try:
            sdata = json.loads(suggestions_path.read_text(encoding="utf-8"))
            first = (sdata.get("suggestions") or [{}])[0]
            first_name = first.get("name", "")
            first_desc = first.get("method", first.get("description", ""))
        except (json.JSONDecodeError, IndexError, KeyError):
            pass

    if first_name:
        short_desc = first_desc[:120] + "..." if len(first_desc) > 120 else first_desc
        click.echo(f"\n  The plan proposes starting with: {first_name}")
        if short_desc:
            click.echo(f"    {short_desc}")

    # Always offer to run — even without suggestions
    exp_name_default = (
        first_name.replace(" ", "-").lower() if first_name else "experiment-1"
    )
    exp_hypothesis = first_desc[:500] if first_desc else ""

    choice = _prompt_numbered(
        "\n  How would you like to proceed?",
        [
            "Run one experiment",
            "Run multiple — run up to N experiments, pause between each",
            "Run until done — fully autonomous until criteria met",
            "Different — I'll describe what to run instead",
            "Skip — I'll run later",
        ],
        default=1,
    )

    if choice.startswith("Skip"):
        pass
    elif choice.startswith("Different"):
        custom = interactive_prompt("Describe the experiment", required=True)
        custom_name = interactive_prompt("Experiment name", default="custom-experiment")
        exp = create_experiment(
            project_dir,
            name=custom_name,
            hypothesis=custom,
        )
        click.echo(f"\n  Created experiment: {exp.experiment_id}")
        click.echo("  Starting orchestrator...\n")
        ctx = click.get_current_context()
        ctx.invoke(
            run,
            project=name,
            experiment_id=exp.experiment_id,
            max_turns=None,
            resume=False,
            max_experiments=None,
        )
    elif choice.startswith("Run multiple"):
        max_exp = int(interactive_prompt("How many experiments?", default="3"))
        exp = create_experiment(
            project_dir,
            name=exp_name_default,
            hypothesis=exp_hypothesis,
        )
        click.echo(f"\n  Created experiment: {exp.experiment_id}")
        click.echo(f"  Starting meta-orchestrator ({max_exp} experiments)...\n")
        ctx = click.get_current_context()
        ctx.invoke(
            run,
            project=name,
            experiment_id=exp.experiment_id,
            max_turns=None,
            resume=False,
            max_experiments=max_exp,
        )
    elif choice.startswith("Run until"):
        exp = create_experiment(
            project_dir,
            name=exp_name_default,
            hypothesis=exp_hypothesis,
        )
        click.echo(f"\n  Created experiment: {exp.experiment_id}")
        click.echo("  Starting meta-orchestrator (autonomous)...\n")
        ctx = click.get_current_context()
        ctx.invoke(
            run,
            project=name,
            experiment_id=exp.experiment_id,
            max_turns=None,
            resume=False,
            auto=True,
            max_experiments=50,
        )
    else:
        # Run one experiment
        exp = create_experiment(
            project_dir,
            name=exp_name_default,
            hypothesis=exp_hypothesis,
        )
        click.echo(f"\n  Created experiment: {exp.experiment_id}")
        click.echo("  Starting orchestrator...\n")
        ctx = click.get_current_context()
        ctx.invoke(
            run,
            project=name,
            experiment_id=exp.experiment_id,
            max_turns=None,
            resume=False,
            max_experiments=None,
        )


def _run_builder_agent_loop(
    builder: object,
    scan_result: object,
    data_summary: object,
    description: str,
    question: str,
    extra_profiles: dict | None = None,
) -> None:
    """Run the interactive agent loop: questions → suggestions → plan."""
    import asyncio

    from urika.agents.runner import get_runner
    from urika.agents.registry import AgentRegistry
    from urika.cli_display import (
        Spinner,
        ThinkingPanel,
        _AGENT_ACTIVITY,
        format_agent_output,
        print_agent,
        print_error,
        print_step,
        print_tool_use,
        thinking_phrase,
    )
    from urika.cli_helpers import interactive_prompt
    from urika.core.builder_prompts import (
        build_planning_prompt,
        build_scoping_prompt,
        build_suggestion_prompt,
    )
    from urika.orchestrator.parsing import (
        _extract_json_blocks,
        parse_suggestions,
    )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()

    # --- Phase 1: Clarifying questions ---
    builder_role = registry.get("project_builder")
    if builder_role is None:
        print_error("Project builder agent not found. Skipping interactive scoping.")
        return

    if scan_result is None:
        print_error("No data scanned. Skipping interactive scoping.")
        return

    # Resolve the actual project directory (where urika.toml lives)
    project_dir = getattr(
        builder, "projects_dir", Path.home() / "urika-projects"
    ) / getattr(builder, "name", "")

    # Create persistent footer panel for the entire builder loop
    panel = ThinkingPanel()
    panel.project = getattr(builder, "name", "")
    panel.activity = thinking_phrase()
    panel.activate()
    panel.start_spinner()

    def _on_builder_msg(msg: object) -> None:
        """Show tool use + update panel from builder agents."""
        try:
            model = getattr(msg, "model", None)
            if model:
                panel.set_model(model)
            if hasattr(msg, "content"):
                for block in msg.content:
                    tool_name = getattr(block, "name", None)
                    if tool_name:
                        inp = getattr(block, "input", {}) or {}
                        detail = ""
                        if isinstance(inp, dict):
                            detail = (
                                inp.get("command", "")
                                or inp.get("file_path", "")
                                or inp.get("pattern", "")
                            )
                        print_tool_use(tool_name, detail)
                        panel.set_thinking(tool_name)
                    else:
                        panel.set_thinking("Thinking…")
        except Exception:
            pass

    answers: dict[str, str] = {}
    context = ""
    max_questions = 10

    print_step("The project builder will ask questions to scope the project.")

    try:
        for i in range(max_questions):
            prompt = build_scoping_prompt(
                scan_result,
                data_summary,
                description,
                context,
                question=question,
                extra_profiles=extra_profiles,
            )
            config = builder_role.build_config(project_dir=project_dir)

            panel.update(agent="project_builder", activity=thinking_phrase())
            result = asyncio.run(runner.run(config, prompt, on_message=_on_builder_msg))

            if not result.success:
                print_error(f"Agent error: {result.error}")
                break

            # Try to parse structured question from JSON block
            blocks = _extract_json_blocks(result.text_output)
            question_text = None
            for block in blocks:
                # Agent signals it has enough context
                if block.get("ready"):
                    question_text = None
                    break
                if "question" in block:
                    question_text = block["question"]
                    if block.get("options"):
                        click.echo(f"\n{question_text}")
                        for j, opt in enumerate(block["options"], 1):
                            click.echo(f"  {j}. {opt}")
                    break

            if question_text is None:
                question_text = result.text_output.strip()
                if not question_text or any(b.get("ready") for b in blocks):
                    break
                click.echo(f"\n{question_text}")

            answer = interactive_prompt("Your answer (or 'done' to move on)")
            if answer.lower() == "done":
                break

            answers[question_text] = answer
            context += f"Q: {question_text}\nA: {answer}\n\n"

        # --- Phase 2: Advisor agent ---
        print_agent("advisor_agent")
        suggest_role = registry.get("advisor_agent")
        if suggest_role is None:
            print_error("Advisor agent not found. Skipping.")
            return

        suggest_prompt = build_suggestion_prompt(description, data_summary, answers)
        suggest_config = suggest_role.build_config(
            project_dir=project_dir, experiment_id=""
        )

        panel.update(
            agent="advisor_agent",
            activity=_AGENT_ACTIVITY.get("advisor_agent", thinking_phrase()),
        )
        suggest_result = asyncio.run(
            runner.run(suggest_config, suggest_prompt, on_message=_on_builder_msg)
        )

        if not suggest_result.success:
            print_error(f"Advisor agent error: {suggest_result.error}")
            return

        suggestions = parse_suggestions(suggest_result.text_output)
        click.echo(format_agent_output(suggest_result.text_output))

        # --- Phase 3: Planning agent ---
        print_agent("planning_agent")
        plan_role = registry.get("planning_agent")
        if plan_role is None:
            print_error("Planning agent not found. Skipping.")
            if suggestions:
                builder.set_initial_suggestions(suggestions)
            return

        plan_prompt = build_planning_prompt(
            suggestions or {}, description, data_summary
        )
        plan_config = plan_role.build_config(project_dir=project_dir, experiment_id="")

        panel.update(
            agent="planning_agent",
            activity=_AGENT_ACTIVITY.get("planning_agent", thinking_phrase()),
        )
        plan_result = asyncio.run(
            runner.run(plan_config, plan_prompt, on_message=_on_builder_msg)
        )

        if not plan_result.success:
            print_error(f"Planning agent error: {plan_result.error}")
            if suggestions:
                builder.set_initial_suggestions(suggestions)
            return

        click.echo(format_agent_output(plan_result.text_output))

    finally:
        panel.cleanup()

    # --- Phase 4: User refinement loop ---
    while True:
        click.echo("")
        choice = _prompt_numbered(
            "What would you like to do?",
            ["Looks good — create the project", "Refine — I have suggestions", "Abort"],
            default=1,
        )
        if choice == "Abort":
            raise click.ClickException("Aborted.")
        if choice.startswith("Looks good"):
            break
        refinement = interactive_prompt("Your suggestions")
        if not refinement:
            continue

        print_agent("advisor_agent")
        refined_prompt = suggest_prompt + f"\n\n## User Refinement\n{refinement}"
        with Spinner(_AGENT_ACTIVITY.get("advisor_agent", thinking_phrase())):
            suggest_result = asyncio.run(
                runner.run(suggest_config, refined_prompt, on_message=_on_builder_msg)
            )
        if suggest_result.success:
            suggestions = parse_suggestions(suggest_result.text_output)
            print_agent("planning_agent")
            plan_prompt = build_planning_prompt(
                suggestions or {}, description, data_summary
            )
            with Spinner(_AGENT_ACTIVITY.get("planning_agent", thinking_phrase())):
                plan_result = asyncio.run(
                    runner.run(plan_config, plan_prompt, on_message=_on_builder_msg)
                )
            if plan_result.success:
                click.echo(format_agent_output(plan_result.text_output))

    # Store final suggestions
    if suggestions:
        builder.set_initial_suggestions(suggestions)


def _ingest_knowledge(
    project_dir: Path,
    scan_result: object,
) -> None:
    """Ingest docs and papers into the project's knowledge store."""
    from urika.knowledge import KnowledgeStore

    store = KnowledgeStore(project_dir)
    ingested = 0
    for f in scan_result.docs + scan_result.papers:
        try:
            store.ingest(str(f))
            ingested += 1
        except Exception:
            pass
    if ingested:
        click.echo(f"Ingested {ingested} files into knowledge base.")


@cli.command("list")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def list_cmd(json_output: bool) -> None:
    """List all registered projects."""
    registry = ProjectRegistry()
    projects = registry.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        projects_data = [
            {"name": name, "path": str(path)} for name, path in projects.items()
        ]
        output_json({"projects": projects_data})
        return

    if not projects:
        click.echo("No projects registered.")
        return

    for name, path in projects.items():
        exists = "  " if path.exists() else "? "
        click.echo(f"{exists}{name}  {path}")


@cli.command()
@click.argument("name", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def status(name: str | None, json_output: bool) -> None:
    """Show project status."""
    name = _ensure_project(name)
    project_path, config = _resolve_project(name)

    experiments = list_experiments(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        exps_data = []
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            exps_data.append(
                {
                    "experiment_id": exp.experiment_id,
                    "name": exp.name,
                    "status": progress.get("status", "unknown"),
                    "runs": len(progress.get("runs", [])),
                }
            )
        output_json(
            {
                "project": config.name,
                "question": config.question,
                "mode": config.mode,
                "path": str(project_path),
                "experiments": exps_data,
            }
        )
        return

    click.echo(f"Project: {config.name}")
    click.echo(f"Question: {config.question}")
    click.echo(f"Mode: {config.mode}")
    click.echo(f"Path: {project_path}")
    click.echo(f"Experiments: {len(experiments)}")

    if experiments:
        click.echo("")
        for exp in experiments:
            progress = load_progress(project_path, exp.experiment_id)
            n_runs = len(progress.get("runs", []))
            exp_status = progress.get("status", "unknown")
            click.echo(
                f"  {exp.experiment_id}: {exp.name} [{exp_status}, {n_runs} runs]"
            )


@cli.group()
def experiment() -> None:
    """Manage experiments within a project."""


@experiment.command("create")
@click.argument("project", required=False, default=None)
@click.argument("name")
@click.option("--hypothesis", default="", help="Experiment hypothesis.")
def experiment_create(project: str, name: str, hypothesis: str) -> None:
    """Create a new experiment in a project."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    exp = create_experiment(project_path, name=name, hypothesis=hypothesis)
    click.echo(f"{exp.experiment_id}")


@experiment.command("list")
@click.argument("project", required=False, default=None)
def experiment_list(project: str) -> None:
    """List experiments in a project."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    experiments = list_experiments(project_path)

    if not experiments:
        click.echo("No experiments yet.")
        return

    for exp in experiments:
        progress = load_progress(project_path, exp.experiment_id)
        n_runs = len(progress.get("runs", []))
        exp_status = progress.get("status", "unknown")
        click.echo(f"  {exp.experiment_id}  {exp.name}  [{exp_status}, {n_runs} runs]")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Show runs for a specific experiment.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def results(project: str, experiment_id: str | None, json_output: bool) -> None:
    """Show project results (leaderboard or experiment runs)."""
    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is not None:
        progress = load_progress(project_path, experiment_id)
        runs = progress.get("runs", [])
        if json_output:
            from urika.cli_helpers import output_json

            output_json({"runs": runs})
            return
        if not runs:
            click.echo("No results yet.")
            return
        for run in runs:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in run.get("metrics", {}).items()
            )
            click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
        return

    leaderboard = load_leaderboard(project_path)
    ranking = leaderboard.get("ranking", [])

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"ranking": ranking})
        return

    if not ranking:
        click.echo("No results yet.")
        return

    for entry in ranking:
        metrics_str = ", ".join(f"{k}={v}" for k, v in entry.get("metrics", {}).items())
        click.echo(f"  #{entry['rank']}  {entry['method']}  {metrics_str}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def methods(project: str, json_output: bool) -> None:
    """List agent-created methods in a project."""
    from urika.core.method_registry import load_methods

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    method_list = load_methods(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        output_json({"methods": method_list})
        return

    if not method_list:
        click.echo("No methods created yet.")
        return

    for m in method_list:
        metrics = m.get("metrics", {})
        nums = {k: v for k, v in metrics.items() if isinstance(v, (int, float))}
        metric_str = ", ".join(f"{k}={v}" for k, v in list(nums.items())[:2])
        click.echo(f"  {m['name']}  [{m.get('status', '')}]  {metric_str}")


@cli.command()
@click.option("--category", default=None, help="Filter by category.")
@click.option("--project", default=None, help="Include project-specific tools.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def tools(category: str | None, project: str | None, json_output: bool) -> None:
    """List available analysis tools."""
    registry = ToolRegistry()
    registry.discover()

    if project is not None:
        project_path, _config = _resolve_project(project)
        registry.discover_project(project_path / "tools")

    if category is not None:
        names = registry.list_by_category(category)
    else:
        names = registry.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        tools_data = []
        for name in names:
            tool = registry.get(name)
            if tool is not None:
                tools_data.append(
                    {
                        "name": tool.name(),
                        "category": tool.category(),
                        "description": tool.description(),
                    }
                )
        output_json({"tools": tools_data})
        return

    if not names:
        click.echo("No tools found.")
        return

    for name in names:
        tool = registry.get(name)
        if tool is not None:
            click.echo(f"  {tool.name()}  [{tool.category()}]  {tool.description()}")


def _determine_next_experiment(
    project_path: Path,
    project_name: str,
    *,
    auto: bool = False,
    panel: object = None,
    instructions: str = "",
) -> str | None:
    """Determine and create the next experiment based on project state.

    Reads methods.json, criteria.json, completed experiments, and the initial
    plan to decide what should run next. If the initial plan is exhausted,
    calls the suggestion agent for next steps.
    """
    import json

    from urika.cli_display import print_step, print_success
    from urika.cli_helpers import interactive_prompt

    # Gather project state
    existing_experiments = list_experiments(project_path)
    completed = [
        e
        for e in existing_experiments
        if load_progress(project_path, e.experiment_id).get("status") == "completed"
    ]

    # Load methods registry
    methods_path = project_path / "methods.json"
    methods_summary = ""
    if methods_path.exists():
        try:
            mdata = json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            if mlist:
                methods_summary = f"{len(mlist)} methods tried. Best: "

                def _best_metric_val(m: dict) -> float:
                    nums = [
                        v
                        for v in m.get("metrics", {}).values()
                        if isinstance(v, (int, float))
                    ]
                    return max(nums) if nums else 0

                best = max(
                    (m for m in mlist if m.get("metrics")),
                    key=_best_metric_val,
                    default=None,
                )
                if best:
                    methods_summary += f"{best['name']} ({best.get('metrics', {})})"
        except (json.JSONDecodeError, KeyError):
            pass

    # Load criteria
    criteria_summary = ""
    criteria_path = project_path / "criteria.json"
    if criteria_path.exists():
        try:
            cdata = json.loads(criteria_path.read_text(encoding="utf-8"))
            versions = cdata.get("versions", [])
            if versions:
                latest = versions[-1]
                ctype = latest.get("criteria", {}).get("type", "unknown")
                criteria_summary = f"Criteria: {ctype} (v{latest['version']})"
        except (json.JSONDecodeError, KeyError):
            pass

    # If user provided instructions, always call advisor agent to think
    # Otherwise fall back to initial plan
    next_suggestion = None
    call_advisor_agent = bool(instructions) or bool(completed)

    if not call_advisor_agent:
        # First experiment, no instructions — use initial plan
        suggestions_path = project_path / "suggestions" / "initial.json"
        if suggestions_path.exists():
            try:
                data = json.loads(suggestions_path.read_text(encoding="utf-8"))
                suggestions = data.get("suggestions", [])
                if suggestions:
                    next_suggestion = suggestions[0]
            except (json.JSONDecodeError, KeyError):
                pass

    # Call suggestion agent to think about next steps
    if next_suggestion is None:
        try:
            import asyncio

            from urika.agents.runner import get_runner
            from urika.agents.registry import AgentRegistry

            runner = get_runner()
            registry = AgentRegistry()
            registry.discover()
            suggest_role = registry.get("advisor_agent")

            if suggest_role is not None:
                context = (
                    f"Project: {project_name}\n"
                    f"Completed experiments: {len(completed)}\n"
                    f"{methods_summary}\n{criteria_summary}\n"
                )
                if instructions:
                    context += f"\nUser instructions: {instructions}\n"
                context += "\nPropose the next experiment."

                config = suggest_role.build_config(
                    project_dir=project_path, experiment_id=""
                )

                from urika.cli_display import (
                    format_agent_output,
                    print_agent,
                    print_tool_use,
                )

                print_agent("advisor_agent")
                if panel is not None:
                    panel.update(agent="advisor_agent", activity="Analyzing…")

                def _on_msg(msg: object) -> None:
                    """Show tool use from suggestion agent."""
                    try:
                        model = getattr(msg, "model", None)
                        if model and panel is not None:
                            panel.set_model(model)
                        if hasattr(msg, "content"):
                            for block in msg.content:
                                tool_name = getattr(block, "name", None)
                                if tool_name:
                                    inp = getattr(block, "input", {}) or {}
                                    detail = ""
                                    if isinstance(inp, dict):
                                        detail = (
                                            inp.get("command", "")
                                            or inp.get("file_path", "")
                                            or inp.get("pattern", "")
                                        )
                                    print_tool_use(tool_name, detail)
                                    if panel is not None:
                                        panel.set_thinking(tool_name)
                                else:
                                    if panel is not None:
                                        panel.set_thinking("Thinking…")
                    except Exception:
                        pass

                result = asyncio.run(runner.run(config, context, on_message=_on_msg))

                if result.success:
                    from urika.orchestrator.parsing import parse_suggestions

                    parsed = parse_suggestions(result.text_output)
                    if parsed and parsed.get("suggestions"):
                        next_suggestion = parsed["suggestions"][0]
                        click.echo(format_agent_output(result.text_output))
        except Exception:
            pass

    if next_suggestion is None:
        return None

    exp_name = next_suggestion.get("name", "auto-experiment").replace(" ", "-").lower()
    description = next_suggestion.get("method", next_suggestion.get("description", ""))
    if instructions:
        description = f"{instructions}\n\n{description}"

    # Show plan and confirm (unless --auto)
    print_step(f"Next experiment: {exp_name}")
    if description:
        short = description[:200] + "..." if len(description) > 200 else description
        click.echo(f"    {short}")
    if methods_summary:
        click.echo(f"    {methods_summary}")
    if criteria_summary:
        click.echo(f"    {criteria_summary}")

    if not auto:
        choice = _prompt_numbered(
            "\n  Proceed?",
            [
                "Yes — create and run it",
                "Different instructions",
                "Skip — exit",
            ],
            default=1,
        )

        if choice.startswith("Skip"):
            return None

        if choice.startswith("Different"):
            instructions = interactive_prompt("Your instructions")
            if instructions:
                description = f"{instructions}\n\n{description}"

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")
    return exp.experiment_id


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment", "experiment_id", default=None, help="Experiment ID to run."
)
@click.option("--max-turns", default=None, type=int, help="Maximum orchestrator turns.")
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Resume a paused or failed experiment.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress verbose tool-use streaming output.",
)
@click.option(
    "--auto",
    is_flag=True,
    default=False,
    help="Fully autonomous — no confirmation prompts.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the next experiment (e.g. 'focus on FOV-constrained models').",
)
@click.option(
    "--max-experiments",
    default=None,
    type=int,
    help="Run multiple experiments via meta-orchestrator (capped mode).",
)
@click.option(
    "--review-criteria",
    is_flag=True,
    default=False,
    help="Ask advisor to review criteria when met (may raise the bar).",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def run(
    project: str,
    experiment_id: str | None,
    max_turns: int | None,
    resume: bool,
    quiet: bool,
    auto: bool,
    instructions: str,
    max_experiments: int | None,
    review_criteria: bool,
    json_output: bool = False,
) -> None:
    """Run an experiment using the orchestrator."""
    try:
        from urika.agents.runner import get_runner
    except ImportError:
        raise click.ClickException(
            "Claude Agent SDK not installed. Run: pip install urika[agents]"
        )
    import signal
    import time

    from urika.cli_display import (
        ThinkingPanel,
        print_agent,
        print_error,
        print_footer,
        print_header,
        print_step,
        print_success,
        print_tool_use,
        print_warning,
    )
    from urika.orchestrator import run_experiment, run_project

    from urika.cli_display import thinking_phrase
    from urika.cli_helpers import interactive_prompt

    # Pick up queued-input callback when invoked from the REPL
    _get_user_input = None
    if os.environ.get("URIKA_REPL"):
        try:
            from urika.repl_commands import _user_input_callback

            _get_user_input = _user_input_callback
        except ImportError:
            pass

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # If --max-turns was not explicitly provided, read from urika.toml
    if max_turns is None:
        import tomllib

        toml_path = project_path / "urika.toml"
        if toml_path.exists():
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                max_turns = data.get("preferences", {}).get(
                    "max_turns_per_experiment", 5
                )
            except Exception:
                max_turns = 5
        else:
            max_turns = 5

    # If no flags provided and not from REPL, show settings dialog
    if (
        not json_output
        and not os.environ.get("URIKA_REPL")
        and experiment_id is None
        and max_experiments is None
        and not auto
        and not resume
        and not instructions
    ):
        click.echo(f"\n  Run settings for {project}:")
        click.echo(f"    Max turns: {max_turns}")

        choice = _prompt_numbered(
            "\n  Proceed?",
            [
                "Run with defaults",
                "Run multiple experiments (meta-orchestrator)",
                "Custom max turns",
                "Skip",
            ],
            default=1,
        )

        if choice.startswith("Skip"):
            return
        elif choice.startswith("Run multiple"):
            max_experiments = int(
                interactive_prompt("How many experiments?", default="3")
            )
        elif choice.startswith("Custom"):
            max_turns = int(
                interactive_prompt("Max turns per experiment", default=str(max_turns))
            )

    # Show header (skip if called from REPL — already has header)
    if not json_output and not os.environ.get("URIKA_REPL"):
        print_header(
            project_name=project,
            agent="orchestrator",
            mode=_config.mode,
        )

    # Create panel early so it's available during experiment selection.
    if json_output:
        panel = None
    else:
        from urika.agents.config import load_runtime_config as _load_rc

        _rc = _load_rc(project_path)
        panel = ThinkingPanel()
        panel.project = f"{project} \u00b7 {_rc.privacy_mode}"
        panel._project_dir = project_path
        panel.activity = "Determining next experiment\u2026"
        panel.activate()
        panel.start_spinner()

    # --- Meta-orchestrator path: --max-experiments delegates to run_project ---
    if max_experiments is not None:
        if not json_output:
            print_step(
                f"Meta-orchestrator: up to {max_experiments} experiments"
                f" (max {max_turns} turns each)"
            )

        # Determine mode: capped auto unless auto flag gives unlimited
        meta_mode = "unlimited" if auto else "capped"

        # Create pause controller and key listener for ESC-to-pause
        from urika.orchestrator.pause import KeyListener, PauseController

        pause_ctrl = PauseController()

        # Start notification bus if configured
        from urika.notifications import build_bus

        notif_bus = build_bus(project_path)
        if notif_bus is not None:
            notif_bus.start(controller=pause_ctrl)

        key_listener: KeyListener | None = None
        if not json_output:

            def _on_pause_esc_meta() -> None:
                if panel is not None:
                    panel.update(pause_requested=True)
                print_warning(
                    "\n\u23f8 Pause requested \u2014 will pause after current turn"
                    " completes..."
                )

            key_listener = KeyListener(
                pause_ctrl, on_pause_requested=_on_pause_esc_meta
            )
            key_listener.start()

        original_handler = signal.getsignal(signal.SIGINT)

        def _cleanup_meta(signum: int, frame: object) -> None:
            if key_listener is not None:
                key_listener.stop()
            print_warning("\n  Autonomous run stopped")
            print_step("  Options:")
            print_step(
                "    urika run --resume              Resume from where you left off"
            )
            print_step("    urika advisor <project> <text>   Chat with advisor first")
            print_step("    urika run --instructions '...'   Run with new instructions")
            raise SystemExit(1)

        signal.signal(signal.SIGINT, _cleanup_meta)

        from datetime import datetime, timezone

        start_ms = int(time.monotonic() * 1000)
        start_iso = datetime.now(timezone.utc).isoformat()
        sdk_runner = get_runner()

        try:
            if json_output:

                def _on_progress(event: str, detail: str = "") -> None:
                    if notif_bus is not None:
                        notif_bus.on_progress(event, detail)

                def _on_message(msg: object) -> None:
                    pass

            else:

                def _on_progress(event: str, detail: str = "") -> None:
                    if event == "turn":
                        print_step(detail)
                        panel.update(turn=detail, activity=thinking_phrase())
                    elif event == "agent":
                        agent_key = (
                            detail.split("\u2014")[0].strip().lower().replace(" ", "_")
                        )
                        print_agent(agent_key)
                        panel.update(agent=agent_key, activity=detail)
                    elif event == "result":
                        print_success(detail)
                    elif event == "phase":
                        print_step(detail)
                        panel.update(activity=detail)
                    # Show pause in footer if requested (from any source)
                    if pause_ctrl.is_pause_requested():
                        panel.update(pause_requested=True)
                    # Dispatch to notification bus
                    if notif_bus is not None:
                        notif_bus.on_progress(event, detail)

                def _on_message(msg: object) -> None:
                    model = getattr(msg, "model", None)
                    if model:
                        panel.set_model(model)
                    content = getattr(msg, "content", None)
                    if content is None:
                        return
                    for block in content:
                        tool_name = getattr(block, "name", None) or getattr(
                            block, "tool_name", None
                        )
                        if tool_name:
                            detail = ""
                            input_data = getattr(block, "input", None) or getattr(
                                block, "tool_input", {}
                            )
                            if isinstance(input_data, dict):
                                if "command" in input_data:
                                    detail = input_data["command"]
                                elif "file_path" in input_data:
                                    detail = input_data["file_path"]
                                elif "pattern" in input_data:
                                    detail = input_data["pattern"]
                            if not quiet:
                                print_tool_use(tool_name, detail)
                            panel.set_thinking(tool_name)
                        else:
                            panel.set_thinking("Thinking\u2026")

            result = asyncio.run(
                run_project(
                    project_path,
                    sdk_runner,
                    mode=meta_mode,
                    max_experiments=max_experiments,
                    max_turns=max_turns,
                    instructions=instructions,
                    review_criteria=review_criteria,
                    on_progress=_on_progress,
                    on_message=_on_message,
                    get_user_input=_get_user_input,
                    pause_controller=pause_ctrl,
                )
            )

        finally:
            if notif_bus is not None:
                notif_bus.stop()
            if key_listener is not None:
                key_listener.stop()
            if panel is not None:
                panel.cleanup()
            signal.signal(signal.SIGINT, original_handler)

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        n_exp = result.get("experiments_run", 0)

        # Send completion notification
        if notif_bus is not None:
            from urika.notifications.events import NotificationEvent

            auto_state = result.get("autonomous_state")
            if auto_state:
                notif_bus.notify(
                    NotificationEvent(
                        event_type="meta_paused",
                        project_name=project,
                        summary=(
                            f"Autonomous run paused after"
                            f" {auto_state.get('experiments_completed', 0)}"
                            " experiment(s)"
                        ),
                        priority="medium",
                    )
                )
            else:
                notif_bus.notify(
                    NotificationEvent(
                        event_type="meta_completed",
                        project_name=project,
                        summary=f"Meta-orchestrator completed: {n_exp} experiment(s)",
                        priority="high",
                    )
                )

        # Aggregate usage from all experiment results
        _meta_tokens_in = 0
        _meta_tokens_out = 0
        _meta_cost_usd = 0.0
        _meta_agent_calls = 0
        for exp_result in result.get("results", []):
            _meta_tokens_in += exp_result.get("tokens_in", 0)
            _meta_tokens_out += exp_result.get("tokens_out", 0)
            _meta_cost_usd += exp_result.get("cost_usd", 0.0)
            _meta_agent_calls += exp_result.get("agent_calls", 0)

        # Record usage for this CLI session
        try:
            from urika.core.usage import record_session

            record_session(
                project_path,
                started=start_iso,
                ended=datetime.now(timezone.utc).isoformat(),
                duration_ms=elapsed_ms,
                tokens_in=_meta_tokens_in,
                tokens_out=_meta_tokens_out,
                cost_usd=_meta_cost_usd,
                agent_calls=_meta_agent_calls,
                experiments_run=n_exp,
            )
        except Exception:
            pass

        if json_output:
            from urika.cli_helpers import output_json

            result["duration_ms"] = elapsed_ms
            output_json(result)
            return

        # Check if paused (autonomous_state present means mid-run pause)
        auto_state = result.get("autonomous_state")
        if auto_state:
            n_done = auto_state.get("experiments_completed", 0)
            print_step(f"\u23f8 Autonomous run paused after {n_done} experiment(s)")
            print_step("  Options:")
            print_step("    urika run --resume              Continue autonomous run")
            print_step("    urika advisor <project> <text>   Chat with advisor first")
            print_step("    urika run --instructions '...'   Resume with new guidance")
            print_footer(duration_ms=elapsed_ms, turns=n_done, status="paused")
            return

        print_success(f"Meta-orchestrator completed: {n_exp} experiment(s) run.")
        print_footer(duration_ms=elapsed_ms, turns=n_exp, status="completed")
        return

    # --- Single experiment path ---
    if experiment_id is None:
        experiments = list_experiments(project_path)
        # Find pending (non-completed) experiments
        pending = [
            e
            for e in experiments
            if load_progress(project_path, e.experiment_id).get("status")
            not in ("completed",)
        ]
        if pending:
            if resume and len(pending) > 1 and not json_output:
                # Multiple resumable — let the user pick
                from urika.cli_helpers import interactive_numbered

                options = []
                for e in pending:
                    p = load_progress(project_path, e.experiment_id)
                    status = p.get("status", "pending")
                    options.append(f"{e.experiment_id} [{status}]")
                choice = interactive_numbered(
                    "\n  Multiple experiments can be resumed:", options
                )
                experiment_id = choice.split(" [")[0]
            else:
                experiment_id = pending[-1].experiment_id
            if not json_output:
                print_step(
                    f"Resuming pending experiment: {experiment_id}",
                    f"({len(pending)} pending)" if len(pending) > 1 else "",
                )
        else:
            # No pending — determine next experiment from state
            experiment_id = _determine_next_experiment(
                project_path,
                project,
                auto=auto or json_output,
                instructions=instructions,
                panel=panel,
            )
            if experiment_id is not None:
                if not json_output:
                    print_step(
                        f"Created new experiment: {experiment_id}",
                        "based on advisor suggestions",
                    )
            elif experiment_id is None:
                if not experiments:
                    raise click.ClickException(
                        "No experiments and no plan found. Create one with:\n"
                        f"  urika experiment create {project} <experiment-name>"
                    )
                experiment_id = experiments[-1].experiment_id
                if not json_output:
                    print_step(f"All experiments completed. Re-running {experiment_id}")

    if not json_output:
        if resume:
            print_step(f"Resuming experiment {experiment_id}")
        else:
            print_step(f"Running experiment {experiment_id} (max {max_turns} turns)")

    # Set experiment ID on panel
    if panel is not None:
        panel.update(experiment_id=experiment_id)

    # Create pause controller and key listener for ESC-to-pause
    from urika.orchestrator.pause import KeyListener, PauseController

    pause_ctrl = PauseController()

    # Start notification bus if configured
    from urika.notifications import build_bus as _build_bus

    notif_bus = _build_bus(project_path)
    if notif_bus is not None:
        notif_bus.set_experiment(experiment_id)
        notif_bus.start(controller=pause_ctrl)

    key_listener: KeyListener | None = None
    if not json_output:

        def _on_pause_esc() -> None:
            if panel is not None:
                panel.update(pause_requested=True)
            print_warning(
                "\n\u23f8 Pause requested \u2014 will pause after current turn completes..."
            )

        key_listener = KeyListener(pause_ctrl, on_pause_requested=_on_pause_esc)
        key_listener.start()

    # Register Ctrl+C handler to clean up lockfile
    def _cleanup_on_interrupt(signum: int, frame: object) -> None:
        if key_listener is not None:
            key_listener.stop()
        print_warning(f"\n  Experiment run stopped ({experiment_id})")
        try:
            from urika.core.session import stop_session

            stop_session(project_path, experiment_id, reason="Stopped by user")
        except Exception:
            # Force remove lockfile if stop_session fails
            lock = project_path / "experiments" / experiment_id / ".lock"
            lock.unlink(missing_ok=True)
        print_step("  Options:")
        print_step("    urika run --resume              Resume from next turn")
        print_step("    urika advisor <project> <text>   Chat with advisor first")
        print_step("    urika run --instructions '...'   Run with new instructions")
        raise SystemExit(1)

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _cleanup_on_interrupt)

    from datetime import datetime, timezone

    start_ms = int(time.monotonic() * 1000)
    start_iso = datetime.now(timezone.utc).isoformat()

    sdk_runner = get_runner()

    # Panel already created and active from experiment selection above
    try:
        if json_output:

            def _on_progress(event: str, detail: str = "") -> None:
                if notif_bus is not None:
                    notif_bus.on_progress(event, detail)

            def _on_message(msg: object) -> None:
                pass

        else:

            def _on_progress(event: str, detail: str = "") -> None:
                if event == "turn":
                    print_step(detail)
                    panel.update(turn=detail, activity=thinking_phrase())
                elif event == "agent":
                    # Extract agent key from "Planning agent — designing method"
                    agent_key = (
                        detail.split("\u2014")[0].strip().lower().replace(" ", "_")
                    )
                    print_agent(agent_key)
                    panel.update(agent=agent_key, activity=detail)
                elif event == "result":
                    print_success(detail)
                elif event == "phase":
                    print_step(detail)
                    panel.update(activity=detail)
                # Show pause in footer if requested (from any source)
                if pause_ctrl.is_pause_requested():
                    panel.update(pause_requested=True)
                # Dispatch to notification bus
                if notif_bus is not None:
                    notif_bus.on_progress(event, detail)

            def _on_message(msg: object) -> None:
                """Handle streaming SDK messages for verbose output."""
                # Capture model name from AssistantMessage
                model = getattr(msg, "model", None)
                if model:
                    panel.set_model(model)

                # Use getattr for safe access — SDK types may vary
                content = getattr(msg, "content", None)
                if content is None:
                    return
                for block in content:
                    tool_name = getattr(block, "name", None) or getattr(
                        block, "tool_name", None
                    )
                    if tool_name:
                        detail = ""
                        input_data = getattr(block, "input", None) or getattr(
                            block, "tool_input", {}
                        )
                        if isinstance(input_data, dict):
                            if "command" in input_data:
                                detail = input_data["command"]
                            elif "file_path" in input_data:
                                detail = input_data["file_path"]
                            elif "pattern" in input_data:
                                detail = input_data["pattern"]
                        if not quiet:
                            print_tool_use(tool_name, detail)
                        panel.set_thinking(tool_name)
                    else:
                        # Text block — agent is thinking
                        panel.set_thinking("Thinking\u2026")

        result = asyncio.run(
            run_experiment(
                project_path,
                experiment_id,
                sdk_runner,
                max_turns=max_turns,
                resume=resume,
                review_criteria=review_criteria,
                on_progress=_on_progress,
                on_message=_on_message,
                instructions=instructions,
                get_user_input=_get_user_input,
                pause_controller=pause_ctrl,
            )
        )

    finally:
        if notif_bus is not None:
            notif_bus.stop()
        if key_listener is not None:
            key_listener.stop()
        if panel is not None:
            panel.cleanup()
        # Restore original handler
        signal.signal(signal.SIGINT, original_handler)

    elapsed_ms = int(time.monotonic() * 1000) - start_ms
    run_status = result.get("status", "unknown")
    turns = result.get("turns", 0)
    error = result.get("error")

    # Send completion/failure notification
    if notif_bus is not None:
        from urika.notifications.events import NotificationEvent as _NE

        if run_status == "completed":
            notif_bus.notify(
                _NE(
                    event_type="experiment_completed",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment completed after {turns} turns",
                    priority="high",
                )
            )
        elif run_status == "failed":
            notif_bus.notify(
                _NE(
                    event_type="experiment_failed",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment failed: {error}",
                    priority="high",
                )
            )
        elif run_status == "paused":
            notif_bus.notify(
                _NE(
                    event_type="experiment_paused",
                    project_name=project,
                    experiment_id=experiment_id,
                    summary=f"Experiment paused after {turns} turns",
                    priority="medium",
                )
            )

    # Record usage for this CLI session
    try:
        from urika.core.usage import record_session

        record_session(
            project_path,
            started=start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=elapsed_ms,
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            cost_usd=result.get("cost_usd", 0.0),
            agent_calls=result.get("agent_calls", 0),
            experiments_run=1,
        )
    except Exception:
        pass

    if json_output:
        from urika.cli_helpers import output_json

        result["duration_ms"] = elapsed_ms
        output_json(result)
        return

    if run_status == "paused":
        print_step(f"\u23f8 Paused after turn {turns}/{max_turns} ({experiment_id})")
        print_step("  Options:")
        print_step("    urika run --resume              Pick up at next turn")
        print_step("    urika advisor <project> <text>   Chat with advisor first")
        print_step("    urika run --instructions '...'   Resume with new guidance")
    elif run_status == "completed":
        print_success(f"Experiment completed after {turns} turns.")
    elif run_status == "failed":
        print_error(f"Experiment failed after {turns} turns: {error}")
    else:
        print_step(f"Experiment finished with status: {run_status} ({turns} turns)")

    print_footer(duration_ms=elapsed_ms, turns=turns, status=run_status)


def _run_report_agent(
    project_path: Path, experiment_id: str, prompt: str, instructions: str = ""
) -> str:
    """Run the report agent and return its text output."""
    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
        from urika.cli_display import Spinner, print_agent

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()

        role = registry.get("report_agent")
        if role is None:
            return ""

        print_agent("report_agent")
        config = role.build_config(
            project_dir=project_path, experiment_id=experiment_id
        )

        if instructions:
            prompt = f"User instructions: {instructions}\n\n{prompt}"

        with Spinner("Writing narrative"):
            result = asyncio.run(
                runner.run(config, prompt, on_message=_make_on_message())
            )

        if result.success and result.text_output:
            return result.text_output.strip()
        return ""
    except ImportError:
        return ""
    except Exception:
        return ""


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment",
    "experiment_id",
    default=None,
    help="Generate report for a specific experiment.",
)
@click.option(
    "--instructions",
    default="",
    help="Guide the report (e.g. 'focus on feature importance findings').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def report(
    project: str,
    experiment_id: str | None,
    instructions: str,
    json_output: bool = False,
) -> None:
    """Generate labbook reports."""
    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    # If no experiment specified, offer selection (like REPL's _pick_experiment)
    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            # No experiments — fall through to project-level reports
            experiment_id = "project"
        elif json_output:
            # JSON mode: default to most recent experiment
            experiment_id = experiments[-1].experiment_id
        else:
            # Build numbered options — most recent first
            reversed_exps = list(reversed(experiments))
            options = []
            for exp in reversed_exps:
                progress = load_progress(project_path, exp.experiment_id)
                status = progress.get("status", "pending")
                runs = len(progress.get("runs", []))
                options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
            options.append("All experiments (generate for each)")
            options.append("Project level (one overarching report)")

            choice = _prompt_numbered(
                "\nSelect experiment for report:", options, default=1
            )

            if choice.startswith("All"):
                experiment_id = "all"
            elif choice.startswith("Project"):
                experiment_id = "project"
            else:
                experiment_id = choice.split(" [")[0]

    try:
        if experiment_id == "all":
            # Generate reports for each experiment
            for exp in list_experiments(project_path):
                click.echo(f"Processing {exp.experiment_id}...")
                try:
                    update_experiment_notes(project_path, exp.experiment_id)
                    generate_experiment_summary(project_path, exp.experiment_id)
                except FileNotFoundError:
                    pass
                narrative = _run_report_agent(
                    project_path,
                    exp.experiment_id,
                    f"Write a detailed narrative report for experiment {exp.experiment_id}.",
                    instructions=instructions,
                )
                if narrative:
                    from urika.core.report_writer import write_versioned

                    narrative_path = (
                        project_path
                        / "experiments"
                        / exp.experiment_id
                        / "labbook"
                        / "narrative.md"
                    )
                    narrative_path.parent.mkdir(parents=True, exist_ok=True)
                    write_versioned(narrative_path, narrative + "\n")
                    if not json_output:
                        click.echo(f"Generated: {narrative_path}")
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"output": "All experiment reports generated."})
                return
            click.echo("All experiment reports generated.")
            return

        if experiment_id == "project":
            # Project-level reports
            from urika.core.readme_generator import write_readme

            try:
                generate_results_summary(project_path)
                generate_key_findings(project_path)
                write_readme(project_path)
            except FileNotFoundError as exc:
                raise click.ClickException(str(exc))

            # Also refresh notes for all experiments
            for exp in list_experiments(project_path):
                try:
                    update_experiment_notes(project_path, exp.experiment_id)
                except FileNotFoundError:
                    pass

            results_path = project_path / "projectbook" / "results-summary.md"
            findings_path = project_path / "projectbook" / "key-findings.md"
            readme_path = project_path / "README.md"

            # Call report agent for project-level narrative
            narrative = _run_report_agent(
                project_path,
                "",
                "Write a project-level narrative report covering all experiments "
                "and the research progression.",
                instructions=instructions,
            )
            if narrative:
                from urika.core.report_writer import write_versioned

                narrative_path = project_path / "projectbook" / "narrative.md"
                narrative_path.parent.mkdir(parents=True, exist_ok=True)
                write_versioned(narrative_path, narrative + "\n")

            if json_output:
                from urika.cli_helpers import output_json

                output_json(
                    {
                        "output": "Project-level reports generated.",
                        "path": str(results_path),
                    }
                )
                return

            click.echo(f"Generated: {results_path}")
            click.echo(f"Generated: {findings_path}")
            click.echo(f"Generated: {readme_path}")
            if narrative:
                click.echo(f"Generated: {narrative_path}")
            return

        # Single experiment report
        try:
            update_experiment_notes(project_path, experiment_id)
            generate_experiment_summary(project_path, experiment_id)
        except FileNotFoundError:
            raise click.ClickException(f"Experiment '{experiment_id}' not found.")
        notes = project_path / "experiments" / experiment_id / "labbook" / "notes.md"
        summary = (
            project_path / "experiments" / experiment_id / "labbook" / "summary.md"
        )

        # Call report agent to write narrative (like REPL)
        narrative = _run_report_agent(
            project_path,
            experiment_id,
            f"Write a detailed narrative report for experiment {experiment_id}.",
            instructions=instructions,
        )
        if narrative:
            from urika.core.report_writer import write_versioned

            narrative_path = (
                project_path
                / "experiments"
                / experiment_id
                / "labbook"
                / "narrative.md"
            )
            narrative_path.parent.mkdir(parents=True, exist_ok=True)
            write_versioned(narrative_path, narrative + "\n")

        if json_output:
            from urika.cli_helpers import output_json

            output_json(
                {
                    "output": f"Report generated for {experiment_id}.",
                    "path": str(summary),
                }
            )
            return

        click.echo(f"Updated: {notes}")
        click.echo(f"Generated: {summary}")
        if narrative:
            click.echo(f"Generated: {narrative_path}")
    except KeyboardInterrupt:
        click.echo("\n  Report generation stopped.")
        click.echo("  Re-run with: urika report [--instructions '...']")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--data", "data_file", default=None, help="Specific data file to inspect."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def inspect(project: str, data_file: str | None, json_output: bool) -> None:
    """Inspect project data: schema, dtypes, missing values, preview."""
    from urika.data.loader import load_dataset

    project = _ensure_project(project)
    project_path, config = _resolve_project(project)

    # Find data file
    if data_file is not None:
        path = (
            Path(data_file)
            if Path(data_file).is_absolute()
            else project_path / data_file
        )
    else:
        # Collect candidate directories: project data/ first, then
        # external paths from config.data_paths and [data].source.
        _supported_exts = (
            "*.csv",
            "*.tsv",
            "*.xlsx",
            "*.xls",
            "*.parquet",
            "*.json",
            "*.jsonl",
        )
        candidate_dirs: list[Path] = []
        data_dir = project_path / "data"
        if data_dir.exists():
            candidate_dirs.append(data_dir)
        # Fall back to configured external data paths
        for dp in config.data_paths:
            p = Path(dp)
            if p.exists() and p not in candidate_dirs:
                candidate_dirs.append(p)
        # Also check [data].source from urika.toml
        try:
            import tomllib

            toml_path = project_path / "urika.toml"
            if toml_path.exists():
                with open(toml_path, "rb") as _f:
                    _toml = tomllib.load(_f)
                _src = _toml.get("data", {}).get("source", "")
                if _src:
                    _src_path = Path(_src)
                    if _src_path.exists() and _src_path not in candidate_dirs:
                        candidate_dirs.append(_src_path)
        except Exception:
            pass

        if not candidate_dirs:
            if json_output:
                from urika.cli_helpers import output_json_error

                output_json_error("No data directory or configured data paths found.")
                raise SystemExit(1)
            raise click.ClickException(
                "No data directory or configured data paths found."
            )

        data_files: list[Path] = []
        for cdir in candidate_dirs:
            if cdir.is_file():
                data_files.append(cdir)
            else:
                for _ext in _supported_exts:
                    data_files.extend(cdir.glob(_ext))
                    # Also search subdirectories for the pattern
                    data_files.extend(cdir.glob(f"**/{_ext}"))
        # Deduplicate while preserving order
        seen: set[Path] = set()
        unique_files: list[Path] = []
        for f in data_files:
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique_files.append(f)
        data_files = unique_files

        if not data_files:
            if json_output:
                from urika.cli_helpers import output_json_error

                output_json_error("No supported data files found in data paths.")
                raise SystemExit(1)
            raise click.ClickException("No supported data files found in data paths.")
        path = data_files[0]
        if len(data_files) > 1 and not json_output:
            click.echo(
                f"Multiple data files found ({len(data_files)}). Using: {path.name}"
            )

    try:
        view = load_dataset(path)
    except Exception as exc:
        raise click.ClickException(f"Failed to load data: {exc}")

    if json_output:
        from urika.cli_helpers import output_json

        columns_data = []
        for col in view.summary.columns:
            columns_data.append(
                {
                    "name": col,
                    "dtype": view.summary.dtypes.get(col, "unknown"),
                    "missing": view.summary.missing_counts.get(col, 0),
                }
            )
        output_json(
            {
                "dataset": path.name,
                "rows": view.summary.n_rows,
                "columns": columns_data,
            }
        )
        return

    click.echo(f"Dataset: {path.name}")
    click.echo(f"Rows: {view.summary.n_rows}")
    click.echo(f"Columns: {view.summary.n_columns}")
    click.echo("")

    # Schema table
    click.echo("Schema:")
    for col in view.summary.columns:
        dtype = view.summary.dtypes.get(col, "unknown")
        missing = view.summary.missing_counts.get(col, 0)
        missing_pct = (
            f" ({100 * missing / view.summary.n_rows:.1f}% missing)"
            if missing > 0
            else ""
        )
        click.echo(f"  {col:<30s} {dtype:<15s}{missing_pct}")
    click.echo("")

    # Preview (first 5 rows)
    click.echo("Preview (first 5 rows):")
    click.echo(view.data.head().to_string(index=False))


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--experiment", "experiment_id", default=None, help="Specific experiment."
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def logs(project: str, experiment_id: str | None, json_output: bool) -> None:
    """Show experiment run log."""
    from urika.core.session import load_session

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments in this project.")
        if len(experiments) == 1:
            experiment_id = experiments[0].experiment_id
        else:
            if json_output:
                # Default to most recent experiment for JSON mode
                experiment_id = experiments[-1].experiment_id
            else:
                # Offer selection when multiple experiments exist
                reversed_exps = list(reversed(experiments))
                options = []
                for exp in reversed_exps:
                    progress_data = load_progress(project_path, exp.experiment_id)
                    status = progress_data.get("status", "pending")
                    runs = len(progress_data.get("runs", []))
                    options.append(f"{exp.experiment_id} [{status}, {runs} runs]")
                choice = _prompt_numbered(
                    "\nSelect experiment to view logs:", options, default=1
                )
                experiment_id = choice.split(" [")[0]

    progress = load_progress(project_path, experiment_id)
    session = load_session(project_path, experiment_id)

    if json_output:
        from urika.cli_helpers import output_json

        runs = progress.get("runs", [])
        data = {
            "experiment_id": experiment_id,
            "runs": runs,
        }
        if session is not None:
            data["status"] = session.status
            data["turns"] = session.current_turn
        output_json(data)
        return

    click.echo(f"Experiment: {experiment_id}")
    if session is not None:
        click.echo(f"Status: {session.status}")
        click.echo(f"Turns: {session.current_turn}")
    click.echo("")

    runs = progress.get("runs", [])
    if not runs:
        click.echo("No runs recorded yet.")
        return

    for run in runs:
        metrics_str = ", ".join(f"{k}={v}" for k, v in run.get("metrics", {}).items())
        click.echo(f"  {run['run_id']}  {run['method']}  {metrics_str}")
        if run.get("hypothesis"):
            click.echo(f"    Hypothesis: {run['hypothesis']}")
        if run.get("observation"):
            click.echo(f"    Observation: {run['observation']}")
        if run.get("next_step"):
            click.echo(f"    Next step: {run['next_step']}")
        click.echo("")


@cli.group()
def knowledge() -> None:
    """Manage project knowledge base."""


@knowledge.command("ingest")
@click.argument("project", required=False, default=None)
@click.argument("source")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_ingest(project: str, source: str, json_output: bool) -> None:
    """Ingest a file or URL into the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    try:
        entry = store.ingest(source)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc))

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"id": entry.id, "title": entry.title, "source_type": entry.source_type}
        )
        return

    click.echo(f'Ingested: {entry.id} "{entry.title}" ({entry.source_type})')


@knowledge.command("search")
@click.argument("project", required=False, default=None)
@click.argument("query")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_search(project: str, query: str, json_output: bool) -> None:
    """Search the knowledge store."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    results_list = store.search(query)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "results": [
                    {
                        "id": e.id,
                        "title": e.title,
                        "source_type": e.source_type,
                        "snippet": e.content[:200],
                    }
                    for e in results_list
                ]
            }
        )
        return

    if not results_list:
        click.echo("No results found.")
        return

    for entry in results_list:
        snippet = entry.content[:100].replace("\n", " ")
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]  {snippet}")


@knowledge.command("list")
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def knowledge_list(project: str, json_output: bool) -> None:
    """List all knowledge entries."""
    from urika.knowledge import KnowledgeStore

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)
    store = KnowledgeStore(project_path)
    entries = store.list_all()

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {
                "entries": [
                    {"id": e.id, "title": e.title, "source_type": e.source_type}
                    for e in entries
                ]
            }
        )
        return

    if not entries:
        click.echo("No knowledge entries yet.")
        return

    for entry in entries:
        click.echo(f"  {entry.id}  {entry.title}  [{entry.source_type}]")


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("text", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def advisor(project: str | None, text: str | None, json_output: bool) -> None:
    """Ask the advisor agent a question about the project."""
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, format_agent_output, print_agent

    from urika.cli_helpers import interactive_prompt

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if text is None:
        text = interactive_prompt("Question or instructions", required=True)

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise click.ClickException(
            "Claude Agent SDK not installed. Run: pip install urika[agents]"
        )

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("advisor_agent")
    if role is None:
        raise click.ClickException("Advisor agent not found.")

    if not json_output:
        print_agent("advisor_agent")
    config = role.build_config(project_dir=project_path, experiment_id="")
    config.max_turns = 25  # Standalone chat needs more turns than in-loop advisor

    # Build richer context (like REPL's _handle_free_text)
    import json as _json

    context = f"Project: {project}\n"
    context += f"\nUser: {text}\n"
    methods_path = project_path / "methods.json"
    if methods_path.exists():
        try:
            mdata = _json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            context += f"\n{len(mlist)} methods tried.\n"
        except Exception:
            pass

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

    try:
        with Spinner("Thinking"):
            result = asyncio.run(
                runner.run(
                    config,
                    context,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Advisor stopped.")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
        _offer_to_run_advisor_suggestions(result.text_output, project, project_path)
    else:
        click.echo(f"Error: {result.error}")


def _offer_to_run_advisor_suggestions(
    advisor_output: str, project_name: str, project_path: Path
) -> None:
    """Parse advisor suggestions and offer to run them via the CLI."""
    from urika.orchestrator.parsing import parse_suggestions

    parsed = parse_suggestions(advisor_output)
    if not parsed or not parsed.get("suggestions"):
        return

    suggestions = parsed["suggestions"]

    from urika.cli_display import _C

    click.echo(
        f"  {_C.BOLD}The advisor suggested {len(suggestions)} experiment(s):{_C.RESET}"
    )
    for i, s in enumerate(suggestions, 1):
        name = s.get("name", f"experiment-{i}")
        click.echo(f"    {i}. {name}")
    click.echo()

    try:
        choice = _prompt_numbered(
            "  Run these experiments?",
            [
                "Yes \u2014 start running now",
                "No \u2014 I'll run later with urika run",
            ],
            default=1,
        )
    except (click.Abort, click.exceptions.Abort):
        return

    if not choice.startswith("Yes"):
        return

    # Create experiment from first suggestion and run it
    suggestion = suggestions[0]
    exp_name = suggestion.get("name", "advisor-experiment").replace(" ", "-").lower()
    description = suggestion.get("method", suggestion.get("description", ""))

    from urika.core.experiment import create_experiment
    from urika.cli_display import print_success

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")

    ctx = click.Context(run)
    ctx.invoke(
        run,
        project=project_name,
        experiment_id=exp.experiment_id,
        max_turns=None,
        resume=False,
        quiet=False,
        auto=False,
        instructions=description,
        max_experiments=None,
        review_criteria=False,
        json_output=False,
    )


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("experiment_id", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Guide evaluation (e.g. 'check for overfitting').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def evaluate(
    project: str | None, experiment_id: str | None, instructions: str, json_output: bool
) -> None:
    """Run the evaluator agent on an experiment."""
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, format_agent_output, print_agent

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments.")
        experiment_id = experiments[-1].experiment_id

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("evaluator")
    if role is None:
        raise click.ClickException("Evaluator agent not found.")

    if not json_output:
        print_agent("evaluator")
    config = role.build_config(project_dir=project_path, experiment_id=experiment_id)

    prompt = f"Evaluate experiment {experiment_id}."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

    if not json_output:
        click.echo(f"  Evaluating {experiment_id}...")
    try:
        with Spinner("Working"):
            result = asyncio.run(
                runner.run(
                    config,
                    prompt,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Evaluation stopped.")
        click.echo("  Re-run with: urika evaluate [--instructions '...']")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.argument("experiment_id", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Guide the plan (e.g. 'consider Bayesian approaches').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def plan(
    project: str | None, experiment_id: str | None, instructions: str, json_output: bool
) -> None:
    """Run the planning agent to design the next method."""
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, format_agent_output, print_agent

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if experiment_id is None:
        experiments = list_experiments(project_path)
        if not experiments:
            raise click.ClickException("No experiments.")
        experiment_id = experiments[-1].experiment_id

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("planning_agent")
    if role is None:
        raise click.ClickException("Planning agent not found.")

    if not json_output:
        print_agent("planning_agent")
    config = role.build_config(project_dir=project_path, experiment_id=experiment_id)

    prompt = "Design the next method based on current results."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

    if not json_output:
        click.echo(f"  Planning for {experiment_id}...")
    try:
        with Spinner("Designing method"):
            result = asyncio.run(
                runner.run(
                    config,
                    prompt,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Planning stopped.")
        click.echo("  Re-run with: urika plan [--instructions '...']")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Optional instructions for the finalizer agent.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def finalize(project: str | None, instructions: str, json_output: bool) -> None:
    """Finalize the project — produce polished methods, report, and presentation."""
    import time

    from datetime import datetime, timezone

    from urika.cli_display import (
        ThinkingPanel,
        print_agent,
        print_error,
        print_success,
        print_tool_use,
    )

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    from urika.agents.config import load_runtime_config

    _rc = load_runtime_config(project_path)

    try:
        from urika.agents.runner import get_runner
        from urika.orchestrator.finalize import finalize_project
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

    if json_output:

        def _on_progress(event: str, detail: str = "") -> None:
            pass

        def _on_message(msg: object) -> None:
            pass

        try:
            result = asyncio.run(
                finalize_project(
                    project_path,
                    runner,
                    _on_progress,
                    _on_message,
                    instructions=instructions,
                )
            )
        except KeyboardInterrupt:
            click.echo("\n  Finalize stopped.")
            if instructions:
                click.echo("  Re-run with: urika finalize --instructions '...'")
            return
    else:
        panel = ThinkingPanel()
        panel.project = f"{project} · {_rc.privacy_mode}"
        panel._project_dir = project_path
        panel.activity = "Finalizing..."
        panel.activate()
        panel.start_spinner()

        def _on_progress(event: str, detail: str = "") -> None:
            if event == "agent":
                agent_key = detail.split("\u2014")[0].strip().lower().replace(" ", "_")
                print_agent(agent_key)
                panel.update(agent=agent_key, activity=detail)
            elif event == "result":
                print_success(detail)

        def _on_message(msg: object) -> None:
            try:
                model = getattr(msg, "model", None)
                if model:
                    panel.set_model(model)
                if hasattr(msg, "content"):
                    for block in msg.content:
                        tool_name = getattr(block, "name", None)
                        if tool_name:
                            inp = getattr(block, "input", {}) or {}
                            detail = ""
                            if isinstance(inp, dict):
                                detail = (
                                    inp.get("command", "")
                                    or inp.get("file_path", "")
                                    or inp.get("pattern", "")
                                )
                            print_tool_use(tool_name, detail)
                            panel.set_thinking(tool_name)
                        else:
                            panel.set_thinking("Thinking\u2026")
            except Exception:
                pass

        try:
            result = asyncio.run(
                finalize_project(
                    project_path,
                    runner,
                    _on_progress,
                    _on_message,
                    instructions=instructions,
                )
            )
        except KeyboardInterrupt:
            panel.cleanup()
            click.echo("\n  Finalize stopped.")
            click.echo("  Re-run with: urika finalize [--instructions '...']")
            return
        finally:
            panel.cleanup()

    # Record finalize usage
    try:
        from urika.core.usage import record_session

        _elapsed_ms = int(time.monotonic() * 1000) - _start_ms
        record_session(
            project_path,
            started=_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=_elapsed_ms,
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            cost_usd=result.get("cost_usd", 0.0),
            agent_calls=result.get("agent_calls", 0),
            experiments_run=0,
        )
    except Exception:
        pass

    if json_output:
        from urika.cli_helpers import output_json

        output_json(result)
        return

    if result.get("success"):
        print_success("Project finalized!")
        click.echo(f"  Methods:       {project_path / 'methods/'}")
        click.echo(
            f"  Final report:  {project_path / 'projectbook' / 'final-report.md'}"
        )
        click.echo(
            f"  Presentation:  "
            f"{project_path / 'projectbook' / 'final-presentation' / 'index.html'}"
        )
        click.echo(f"  Reproduce:     {project_path / 'reproduce.sh'}")
    else:
        print_error(f"Finalization failed: {result.get('error', 'unknown')}")


@cli.command("update")
@click.argument("project", required=False, default=None)
@click.option(
    "--field",
    type=click.Choice(
        ["description", "question", "mode"],
        case_sensitive=False,
    ),
    default=None,
    help="Field to update.",
)
@click.option("--value", default=None, help="New value.")
@click.option(
    "--reason",
    default="",
    help="Why this change was made.",
)
@click.option(
    "--history",
    is_flag=True,
    help="Show revision history.",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def update_project(
    project: str | None,
    field: str | None,
    value: str | None,
    reason: str,
    history: bool,
    json_output: bool,
) -> None:
    """Update project description, question, or mode.

    Changes are versioned — previous values are preserved
    with timestamps in revisions.json.

    Examples:

        urika update my-study --field question --value "Does X predict Y?"

        urika update my-study --field description --reason "Added new variables"

        urika update my-study --history
    """
    from urika.cli_display import (
        print_step,
        print_success,
    )
    from urika.cli_helpers import interactive_numbered, interactive_prompt

    project = _ensure_project(project)
    project_path, config = _resolve_project(project)

    # Show history
    if history:
        from urika.core.revisions import load_revisions

        revs = load_revisions(project_path)

        if json_output:
            from urika.cli_helpers import output_json

            output_json({"revisions": revs})
            return

        if not revs:
            click.echo("  No revisions recorded.")
            return
        click.echo(f"\n  Revision history for {project}:\n")
        for r in revs:
            ts = r["timestamp"][:19].replace("T", " ")
            click.echo(f"  #{r['revision']}  {ts}  [{r['field']}]")
            click.echo(
                f"    Old: {r['old_value'][:80]}"
                f"{'…' if len(r['old_value']) > 80 else ''}"
            )
            click.echo(
                f"    New: {r['new_value'][:80]}"
                f"{'…' if len(r['new_value']) > 80 else ''}"
            )
            if r.get("reason"):
                click.echo(f"    Why: {r['reason']}")
            click.echo()
        return

    # JSON mode requires --field and --value
    if json_output and (field is None or value is None):
        from urika.cli_helpers import output_json_error

        output_json_error("--field and --value are required in --json mode")
        raise SystemExit(1)

    # Interactive if no field specified
    if field is None:
        click.echo(f"\n  Current project config for {project}:\n")
        click.echo(f"  Description: {config.description[:100]}")
        click.echo(f"  Question:    {config.question[:100]}")
        click.echo(f"  Mode:        {config.mode}")
        click.echo()
        field = interactive_numbered(
            "  Field to update:",
            ["description", "question", "mode"],
            default=1,
        )

    # Show current value and get new value
    current = getattr(config, field, "")
    if value is None:
        click.echo(f"\n  Current {field}:")
        click.echo(f"  {current}\n")
        if field == "mode":
            from urika.core.models import VALID_MODES

            value = interactive_numbered(
                f"  New {field}:",
                sorted(VALID_MODES),
                default=1,
            )
        else:
            value = interactive_prompt(f"New {field}", required=True)

    if not value:
        if json_output:
            from urika.cli_helpers import output_json_error

            output_json_error("No value provided.")
            raise SystemExit(1)
        click.echo("  No change.")
        return

    if value == current:
        if json_output:
            from urika.cli_helpers import output_json

            output_json({"unchanged": True, "field": field, "value": value})
            return
        click.echo("  Value unchanged.")
        return

    if not json_output and not reason:
        reason = interactive_prompt(
            "Reason for change (optional, Enter to skip)",
            default="",
        )

    from urika.core.revisions import update_project_field

    rev = update_project_field(
        project_path,
        field=field,
        new_value=value,
        reason=reason,
    )

    if json_output:
        from urika.cli_helpers import output_json

        output_json(rev)
        return

    print_success(f"Updated {field} (revision #{rev['revision']})")
    print_step("Previous value preserved in revisions.json")


@cli.command("build-tool")
@click.argument("project", required=False, default=None)
@click.argument("instructions", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def build_tool(
    project: str | None, instructions: str | None, json_output: bool
) -> None:
    """Build a custom tool for the project.

    Give the tool builder agent instructions to create a specific tool,
    install a package, or build a data reader. Examples:

    \b
      urika build-tool my-project "create an EEG epoch extractor using MNE"
      urika build-tool my-project "build a tool that computes ICC using pingouin"
      urika build-tool my-project "install librosa and create an audio feature extractor"
    """
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, format_agent_output, print_agent
    from urika.cli_helpers import interactive_prompt

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if instructions is None:
        instructions = interactive_prompt(
            "Describe the tool to build (e.g., 'create a correlation heatmap tool using seaborn')",
            required=True,
        )

    try:
        from urika.agents.runner import get_runner
        from urika.agents.registry import AgentRegistry
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    registry = AgentRegistry()
    registry.discover()
    role = registry.get("tool_builder")
    if role is None:
        raise click.ClickException("Tool builder agent not found.")

    if not json_output:
        print_agent("tool_builder")
    config = role.build_config(project_dir=project_path)

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()

    try:
        with Spinner("Building tool"):
            result = asyncio.run(
                runner.run(
                    config,
                    instructions,
                    on_message=_make_on_message()
                    if not json_output
                    else lambda m: None,
                )
            )
    except KeyboardInterrupt:
        click.echo("\n  Tool build stopped.")
        return

    _record_agent_usage(project_path, result, _start_iso, _start_ms)

    if json_output:
        from urika.cli_helpers import output_json

        output_json(
            {"output": result.text_output.strip() if result.success else result.error}
        )
        return

    if result.success and result.text_output:
        click.echo(format_agent_output(result.text_output))
    else:
        click.echo(f"Error: {result.error}")


@cli.command()
@click.argument("project", required=False, default=None)
@click.option(
    "--instructions",
    default="",
    help="Guide the presentation (e.g. 'emphasize ensemble results').",
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def present(project: str | None, instructions: str, json_output: bool) -> None:
    """Generate a presentation for an experiment."""
    import asyncio
    import time

    from datetime import datetime, timezone

    from urika.cli_display import Spinner, print_agent, print_success

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    experiments = list_experiments(project_path)
    if not experiments:
        raise click.ClickException("No experiments.")

    try:
        from urika.agents.runner import get_runner
        from urika.orchestrator.loop import _generate_presentation, _noop_callback
    except ImportError:
        raise click.ClickException("Claude Agent SDK not installed.")

    runner = get_runner()
    on_msg = (lambda m: None) if json_output else _make_on_message()

    if json_output:
        # JSON mode: default to most recent experiment, no interactive prompt
        choice = f"{experiments[-1].experiment_id} [auto]"
    else:
        # Build options — most recent first, plus all/project choices
        reversed_exps = list(reversed(experiments))
        options = []
        for exp in reversed_exps:
            progress = load_progress(project_path, exp.experiment_id)
            exp_status = progress.get("status", "pending")
            runs = len(progress.get("runs", []))
            options.append(f"{exp.experiment_id} [{exp_status}, {runs} runs]")
        options.append("All experiments (generate for each)")
        options.append("Project level (one overarching presentation)")

        choice = _prompt_numbered("\n  Select:", options, default=1)

    _start_ms = int(time.monotonic() * 1000)
    _start_iso = datetime.now(timezone.utc).isoformat()
    _pres_tokens_in = 0
    _pres_tokens_out = 0
    _pres_cost = 0.0
    _pres_calls = 0

    try:
        if choice.startswith("All"):
            # Generate presentation for each experiment
            for exp in experiments:
                if not json_output:
                    print_agent("presentation_agent")
                with Spinner("Creating slides"):
                    _pu = asyncio.run(
                        _generate_presentation(
                            project_path,
                            exp.experiment_id,
                            runner,
                            _noop_callback,
                            on_message=on_msg,
                            instructions=instructions,
                        )
                    )
                    _pres_tokens_in += _pu.get("tokens_in", 0)
                    _pres_tokens_out += _pu.get("tokens_out", 0)
                    _pres_cost += _pu.get("cost_usd", 0.0)
                    _pres_calls += _pu.get("agent_calls", 0)
                if not json_output:
                    print_success(
                        f"Saved to experiments/{exp.experiment_id}/presentation/index.html"
                    )
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(project_path / "experiments")})
                return
            print_success("All presentations generated")
        elif choice.startswith("Project"):
            # Project-level presentation
            if not json_output:
                print_agent("presentation_agent")
            with Spinner("Creating slides"):
                _pu = asyncio.run(
                    _generate_presentation(
                        project_path,
                        "",
                        runner,
                        _noop_callback,
                        on_message=on_msg,
                        instructions=instructions,
                    )
                )
                _pres_tokens_in += _pu.get("tokens_in", 0)
                _pres_tokens_out += _pu.get("tokens_out", 0)
                _pres_cost += _pu.get("cost_usd", 0.0)
                _pres_calls += _pu.get("agent_calls", 0)
            pres_path = project_path / "projectbook" / "presentation" / "index.html"
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(pres_path)})
                return
            print_success("Saved to projectbook/presentation/index.html")
        else:
            # Single experiment
            exp_id = choice.split(" [")[0]
            if not json_output:
                print_agent("presentation_agent")
            with Spinner("Creating slides"):
                _pu = asyncio.run(
                    _generate_presentation(
                        project_path,
                        exp_id,
                        runner,
                        _noop_callback,
                        on_message=on_msg,
                        instructions=instructions,
                    )
                )
                _pres_tokens_in += _pu.get("tokens_in", 0)
                _pres_tokens_out += _pu.get("tokens_out", 0)
                _pres_cost += _pu.get("cost_usd", 0.0)
                _pres_calls += _pu.get("agent_calls", 0)
            pres_path = (
                project_path / "experiments" / exp_id / "presentation" / "index.html"
            )
            if json_output:
                from urika.cli_helpers import output_json

                output_json({"path": str(pres_path)})
                return
            print_success(f"Saved to experiments/{exp_id}/presentation/index.html")
    except KeyboardInterrupt:
        click.echo("\n  Presentation stopped.")
        click.echo("  Re-run with: urika present [--instructions '...']")

    # Record presentation usage
    try:
        from urika.core.usage import record_session

        _elapsed_ms = int(time.monotonic() * 1000) - _start_ms
        record_session(
            project_path,
            started=_start_iso,
            ended=datetime.now(timezone.utc).isoformat(),
            duration_ms=_elapsed_ms,
            tokens_in=_pres_tokens_in,
            tokens_out=_pres_tokens_out,
            cost_usd=_pres_cost,
            agent_calls=_pres_calls,
            experiments_run=0,
        )
    except Exception:
        pass


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def criteria(project: str | None, json_output: bool) -> None:
    """Show current project criteria."""
    from urika.core.criteria import load_criteria

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    c = load_criteria(project_path)

    if json_output:
        from urika.cli_helpers import output_json

        if c is None:
            output_json({"criteria": None})
        else:
            output_json(
                {
                    "criteria": {
                        "version": c.version,
                        "set_by": c.set_by,
                        **c.criteria,
                    }
                }
            )
        return

    if c is None:
        click.echo("  No criteria set.")
        return
    click.echo(f"\n  Criteria v{c.version} (set by {c.set_by})")
    click.echo(f"  Type: {c.criteria.get('type', 'unknown')}")
    threshold = c.criteria.get("threshold", {})
    primary = threshold.get("primary", {})
    if primary:
        click.echo(
            f"  Primary: {primary.get('metric')} "
            f"{primary.get('direction', '>')} {primary.get('target')}"
        )
    click.echo()


@cli.command()
@click.argument("project", required=False, default=None)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def usage(project: str | None, json_output: bool) -> None:
    """Show usage stats for a project."""
    from urika.core.usage import format_usage, get_last_session, get_totals

    if project:
        project = _ensure_project(project)
        project_path, _config = _resolve_project(project)
        last = get_last_session(project_path)
        totals = get_totals(project_path)

        if json_output:
            from urika.cli_helpers import output_json

            output_json({"session": last or {}, "total": totals})
            return

        click.echo(f"\n  Usage: {project}")
        click.echo(format_usage(last, totals))
    else:
        # All projects
        registry_obj = ProjectRegistry()
        projects = registry_obj.list_all()

        if json_output:
            from urika.cli_helpers import output_json

            all_usage = {}
            for name, path in projects.items():
                all_usage[name] = get_totals(path)
            output_json({"projects": all_usage})
            return

        if not projects:
            click.echo("  No projects.")
            return
        click.echo("\n  Usage across all projects:")
        for name, path in projects.items():
            totals = get_totals(path)
            if totals.get("sessions", 0) > 0:
                tokens = totals.get("total_tokens_in", 0) + totals.get(
                    "total_tokens_out", 0
                )
                tok_str = f"{tokens / 1000:.0f}K" if tokens >= 1000 else str(tokens)
                click.echo(
                    f"  {name}: {totals['sessions']} sessions · "
                    f"{tok_str} tokens · ~${totals['total_cost_usd']:.2f}"
                )
    click.echo()


@cli.command("config")
@click.argument("project", required=False, default=None)
@click.option("--show", is_flag=True, help="Show current settings.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def config_command(
    project: str | None,
    show: bool,
    json_output: bool,
) -> None:
    """View or configure privacy mode and models.

    Without PROJECT, configures global defaults (~/.urika/settings.toml).
    With PROJECT, configures that project's urika.toml.

    Examples:

        urika config --show              # show global defaults
        urika config                     # interactive setup (global)
        urika config my-project --show   # show project settings
        urika config my-project          # interactive setup (project)
    """
    from urika.cli_display import print_step
    from urika.cli_helpers import UserCancelled

    # ── Determine target: global or project ──
    is_project = False
    project_path = None
    if project is not None:
        is_project = True
        try:
            project_path, _config = _resolve_project(project)
        except click.ClickException:
            raise

    # ── Load current settings ──
    if is_project:
        import tomllib

        toml_path = project_path / "urika.toml"
        with open(toml_path, "rb") as f:
            settings = tomllib.load(f)
    else:
        from urika.core.settings import load_settings

        settings = load_settings()

    # ── Show mode ──
    if show:
        if json_output:
            from urika.cli_helpers import output_json

            output_json(settings)
            return

        label = f"Project: {project}" if is_project else "Global defaults"
        click.echo(f"\n  {label}\n")
        p = settings.get("privacy", {})
        r = settings.get("runtime", {})
        mode = p.get("mode", "open")
        print_step(f"Privacy mode: {mode}")
        eps = p.get("endpoints", {})
        for ep_name, ep in eps.items():
            if isinstance(ep, dict):
                url = ep.get("base_url", "")
                key = ep.get("api_key_env", "")
                label_ep = f"  {ep_name}: {url}"
                if key:
                    label_ep += f" (key: ${key})"
                print_step(label_ep)
        if r.get("model"):
            print_step(f"Default model: {r['model']}")
        models = r.get("models", {})
        for agent_name, agent_cfg in models.items():
            if isinstance(agent_cfg, dict):
                m = agent_cfg.get("model", "")
                ep = agent_cfg.get("endpoint", "open")
                print_step(f"  {agent_name}: {m} (endpoint: {ep})")
            elif isinstance(agent_cfg, str):
                print_step(f"  {agent_name}: {agent_cfg}")
        click.echo()
        return

    # ── Interactive setup ──
    current_mode = settings.get("privacy", {}).get("mode", "open")
    click.echo(f"\n  Current privacy mode: {current_mode}\n")

    try:
        _config_interactive(
            session=settings,
            current_mode=current_mode,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")
        return


def _config_interactive(*, session, current_mode, is_project, project_path):
    """Interactive config setup. Raises UserCancelled on cancel/ESC."""
    import click
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import (
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )

    _CLOUD_MODELS = [
        ("claude-sonnet-4-5", "Best balance of speed and quality (recommended)"),
        ("claude-opus-4-6", "Most capable, slower, higher cost"),
        ("claude-haiku-4-5", "Fastest, lowest cost, less capable"),
    ]

    settings = session

    mode = interactive_numbered(
        "  Privacy mode:",
        [
            "open — all agents use Claude API (cloud models only)",
            "private — all agents use local/server models (nothing leaves your network)",
            "hybrid — most agents use Claude API, data agents use local models",
        ],
        default={"open": 1, "private": 2, "hybrid": 3}.get(current_mode, 1),
    )
    mode = mode.split(" —")[0].strip()

    # Warn if changing from private/hybrid to less private
    if current_mode == "private" and mode in ("open", "hybrid"):
        print_warning(
            f"Changing from private to {mode} — agents will send data to cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return
    elif current_mode == "hybrid" and mode == "open":
        print_warning(
            "Changing from hybrid to open — "
            "ALL agents (including data agent) will use cloud APIs."
        )
        if not interactive_confirm("  Continue?", default=False):
            click.echo("  Cancelled.")
            return

    settings.setdefault("privacy", {})["mode"] = mode

    # ── Open mode: pick cloud model ──
    if mode == "open":
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Default model for all agents:",
            options,
            default=1,
        )
        model_name = choice.split(" —")[0].strip()
        settings.setdefault("runtime", {})["model"] = model_name
        # Clear any private endpoints
        settings.get("privacy", {}).pop("endpoints", None)
        print_success(f"Mode: open · Model: {model_name}")

    # ── Private mode: configure endpoint + model ──
    elif mode == "private":
        click.echo()
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        # API key (optional for local servers, required for remote)
        from urika.cli_helpers import interactive_prompt

        key_env = interactive_prompt(
            "  API key env var NAME, not the key itself (e.g. INFERENCE_HUB_KEY)",
            default="",
        )
        if key_env:
            ep["api_key_env"] = key_env

        from urika.cli_helpers import interactive_prompt

        model_name = interactive_prompt(
            "  Model name (e.g. qwen3:14b, mistral:7b)",
        )
        settings.setdefault("runtime", {})["model"] = model_name
        print_success(f"Mode: private · Endpoint: {ep_url} · Model: {model_name}")

    # ── Hybrid mode: cloud model + private endpoint for data agents ──
    elif mode == "hybrid":
        # Cloud model for most agents
        click.echo()
        options = [f"{m} — {desc}" for m, desc in _CLOUD_MODELS]
        choice = interactive_numbered(
            "  Cloud model for most agents:",
            options,
            default=1,
        )
        cloud_model = choice.split(" —")[0].strip()
        settings.setdefault("runtime", {})["model"] = cloud_model

        # Private endpoint for data agents
        click.echo()
        click.echo("  Data Agent and Tool Builder must use a private model.")
        ep_type = interactive_numbered(
            "  Private endpoint type:",
            [
                "Ollama (localhost:11434)",
                "LM Studio (localhost:1234)",
                "vLLM / LiteLLM server (network)",
                "Custom server URL",
            ],
            default=1,
        )
        if ep_type.startswith("Ollama"):
            ep_url = "http://localhost:11434"
        elif ep_type.startswith("LM Studio"):
            ep_url = "http://localhost:1234"
        elif ep_type.startswith("vLLM"):
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt(
                "  Server URL without /v1 (e.g. http://192.168.1.100:4200)"
            )
        else:
            from urika.cli_helpers import interactive_prompt

            ep_url = interactive_prompt("  Server URL")

        p = settings.setdefault("privacy", {})
        ep = p.setdefault("endpoints", {}).setdefault("private", {})
        ep["base_url"] = ep_url

        if "localhost" not in ep_url and "127.0.0.1" not in ep_url:
            from urika.cli_helpers import interactive_prompt

            key_env = interactive_prompt(
                "  API key environment variable name",
                default="",
            )
            if key_env:
                ep["api_key_env"] = key_env

        from urika.cli_helpers import interactive_prompt

        private_model = interactive_prompt(
            "  Private model for data agents (e.g. qwen3:14b)",
        )

        # Set per-agent overrides
        models = settings.setdefault("runtime", {}).setdefault("models", {})
        models["data_agent"] = {"model": private_model, "endpoint": "private"}
        # tool_builder uses cloud by default in hybrid (doesn't touch raw data)

        print_success(
            f"Mode: hybrid · Cloud: {cloud_model} · "
            f"Data agents: {private_model} via {ep_url}"
        )

    # ── Save ──
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
        print_step(f"Saved to {project_path / 'urika.toml'}")
    else:
        from urika.core.settings import save_settings

        save_settings(settings)
        from urika.core.settings import _settings_path

        print_step(f"Saved to {_settings_path()}")

    click.echo()
    click.echo(
        "  Tip: for per-agent model overrides, edit the [runtime.models] "
        "section in urika.toml directly."
    )
    click.echo()


@cli.command("notifications")
@click.option("--show", is_flag=True, help="Show current notification config.")
@click.option("--test", "send_test", is_flag=True, help="Send a test notification.")
@click.option("--disable", is_flag=True, help="Disable all notifications.")
@click.option("--project", default=None, help="Configure for a specific project.")
def notifications_command(
    show: bool,
    send_test: bool,
    disable: bool,
    project: str | None,
) -> None:
    """Configure notification channels (email, Slack, Telegram).

    Examples:

        urika notifications              # interactive setup (global)
        urika notifications --show       # show current config
        urika notifications --test       # send test notification
        urika notifications --disable    # disable notifications
        urika notifications --project X  # configure for project X
    """
    from urika.cli_display import print_success
    from urika.cli_helpers import UserCancelled

    # ── Determine target: global or project ──
    is_project = False
    project_path = None
    if project is not None:
        is_project = True
        try:
            project_path, _config = _resolve_project(project)
        except click.ClickException:
            raise

    # ── Load current settings ──
    if is_project:
        import tomllib

        toml_path = project_path / "urika.toml"
        with open(toml_path, "rb") as f:
            settings = tomllib.load(f)
    else:
        from urika.core.settings import load_settings

        settings = load_settings()

    notif = settings.get("notifications", {})

    # ── Disable mode ──
    if disable:
        settings.setdefault("notifications", {})["enabled"] = False
        _save_notification_settings(settings, is_project, project_path)
        print_success("Notifications disabled.")
        return

    # ── Show mode ──
    if show:
        _show_notification_config(notif)
        return

    # ── Test mode ──
    if send_test:
        _send_test_notification(notif, project_path=project_path)
        return

    # ── Interactive setup ──
    try:
        _notifications_interactive(
            settings=settings,
            is_project=is_project,
            project_path=project_path,
        )
    except UserCancelled:
        click.echo("\n  Cancelled.")


def _show_notification_config(notif: dict) -> None:
    """Display current notification config with masked credentials."""
    from urika.cli_display import print_step
    from urika.core.secrets import list_secrets

    enabled = notif.get("enabled", False)
    click.echo(f"\n  Notifications: {'enabled' if enabled else 'disabled'}\n")

    # Email
    email = notif.get("email", {})
    if email.get("to"):
        to_addrs = email["to"] if isinstance(email["to"], list) else [email["to"]]
        from_addr = email.get("from_addr", "")
        server = email.get("smtp_server", "smtp.gmail.com")
        port = email.get("smtp_port", 587)
        print_step(f"Email: {from_addr} -> {', '.join(to_addrs)} (via {server}:{port})")
    else:
        print_step("Email: not configured")

    # Slack
    slack = notif.get("slack", {})
    if slack.get("channel"):
        print_step(f"Slack: {slack['channel']} (configured)")
    else:
        print_step("Slack: not configured")

    # Telegram
    telegram = notif.get("telegram", {})
    if telegram.get("chat_id"):
        print_step(f"Telegram: chat {telegram['chat_id']} (configured)")
    else:
        print_step("Telegram: not configured")

    # Show stored secrets (masked)
    secrets = list_secrets()
    notif_keys = [
        k
        for k in secrets
        if k
        in (
            "URIKA_EMAIL_PASSWORD",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        )
    ]
    if notif_keys:
        click.echo()
        print_step("Stored credentials:")
        for k in notif_keys:
            print_step(f"  {k}: ****")

    click.echo()


def _send_test_notification(notif: dict, project_path: Path | None = None) -> None:
    """Send a test notification through all configured channels."""
    from urika.cli_display import print_error, print_success, print_warning
    from urika.notifications.events import NotificationEvent

    # Use build_bus for proper global+project config resolution
    if project_path is not None:
        from urika.notifications import build_bus

        bus = build_bus(project_path)
        if bus is None:
            print_warning("No notification channels enabled for this project.")
            return

        event = NotificationEvent(
            event_type="test",
            project_name=project_path.name,
            summary="Test notification from Urika",
            priority="medium",
        )
        for ch in bus.channels:
            try:
                ch.send(event)
                print_success(f"Test sent via {type(ch).__name__}")
            except Exception as exc:
                print_error(f"{type(ch).__name__} failed: {exc}")
        return

    # Global test (no project) — test each channel from raw config
    event = NotificationEvent(
        event_type="test",
        project_name="test",
        summary="Test notification from Urika",
        priority="medium",
    )

    sent = False

    # Test email
    email_cfg = notif.get("email", {})
    if email_cfg.get("to"):
        try:
            from urika.notifications.email_channel import EmailChannel

            ch = EmailChannel(email_cfg)
            ch.send(event)
            to_addrs = email_cfg["to"]
            if isinstance(to_addrs, list):
                to_addrs = ", ".join(to_addrs)
            print_success(f"Test email sent to {to_addrs}")
            sent = True
        except Exception as exc:
            print_error(f"Email failed: {exc}")

    # Test Slack
    slack_cfg = notif.get("slack", {})
    if slack_cfg.get("channel"):
        try:
            from urika.notifications.slack_channel import SlackChannel

            ch = SlackChannel(slack_cfg)
            ch.send(event)
            print_success(f"Test Slack message sent to {slack_cfg['channel']}")
            sent = True
        except ImportError:
            print_warning("slack-sdk not installed: pip install slack-sdk")
        except Exception as exc:
            print_error(f"Slack failed: {exc}")

    # Test Telegram
    telegram_cfg = notif.get("telegram", {})
    if telegram_cfg.get("chat_id"):
        try:
            from urika.notifications.telegram_channel import TelegramChannel

            ch = TelegramChannel(telegram_cfg)
            ch.send(event)
            print_success(
                f"Test Telegram message sent to chat {telegram_cfg['chat_id']}"
            )
            sent = True
        except ImportError:
            print_warning(
                "python-telegram-bot not installed: pip install python-telegram-bot"
            )
        except Exception as exc:
            print_error(f"Telegram failed: {exc}")

    if not sent:
        print_warning("No channels configured. Run: urika notifications")


def _notifications_interactive(*, settings, is_project, project_path):
    """Interactive notification setup. Raises UserCancelled on cancel/ESC."""
    if is_project:
        _notifications_project_setup(settings=settings, project_path=project_path)
        return

    _notifications_global_setup(settings=settings, project_path=project_path)


def _notifications_project_setup(*, settings, project_path):
    """Project-level notification setup — select channels + extra recipients."""
    import click
    import tomllib
    from urika.cli_display import print_step, print_success, print_warning
    from urika.cli_helpers import interactive_confirm, interactive_prompt

    # Load global config to show what's available
    global_notif: dict = {}
    global_path = Path.home() / ".urika" / "settings.toml"
    if global_path.exists():
        try:
            with open(global_path, "rb") as f:
                data = tomllib.load(f)
            global_notif = data.get("notifications", {})
        except Exception:
            pass

    # Check what's configured globally
    has_email = bool(global_notif.get("email", {}).get("to"))
    has_slack = bool(global_notif.get("slack", {}).get("channel"))
    has_telegram = bool(global_notif.get("telegram", {}).get("chat_id"))

    if not has_email and not has_slack and not has_telegram:
        print_warning(
            "No notification channels configured globally.\n"
            "  Run 'urika notifications' (without --project) to set up channels first."
        )
        return

    click.echo("\n  Project notification setup\n")

    # Show available global channels
    click.echo("  Available channels (from global settings):")
    if has_email:
        to = global_notif["email"]["to"]
        if isinstance(to, list):
            to = ", ".join(to)
        click.echo(
            f"    Email:    {global_notif['email'].get('from_addr', '?')} -> {to}"
        )
    if has_slack:
        click.echo(f"    Slack:    {global_notif['slack']['channel']}")
    if has_telegram:
        click.echo(f"    Telegram: chat {global_notif['telegram']['chat_id']}")
    click.echo()

    # Ask which channels to enable
    channels = []
    if has_email and interactive_confirm("Enable email notifications?", default=True):
        channels.append("email")
    if has_slack and interactive_confirm("Enable Slack notifications?", default=True):
        channels.append("slack")
    if has_telegram and interactive_confirm(
        "Enable Telegram notifications?", default=True
    ):
        channels.append("telegram")

    if not channels:
        print_step("No channels enabled.")
        return

    # Ask for extra email recipients
    extra_to: list[str] = []
    if "email" in channels:
        extra_raw = interactive_prompt(
            "Extra email recipients for this project (comma-separated, or blank)",
            default="",
        )
        if extra_raw.strip():
            extra_to = [a.strip() for a in extra_raw.split(",") if a.strip()]

    # Save to project urika.toml
    notif: dict = {"channels": channels}
    if extra_to:
        notif["email"] = {"to": extra_to}
    settings["notifications"] = notif
    _save_notification_settings(settings, is_project=True, project_path=project_path)

    print_success(f"Notifications enabled: {', '.join(channels)}")
    if extra_to:
        click.echo(f"  Extra recipients: {', '.join(extra_to)}")
    click.echo()


def _notifications_global_setup(*, settings, project_path):
    """Global notification setup — configure channel settings."""

    import click
    from urika.cli_display import print_success
    from urika.cli_helpers import (
        interactive_confirm,
        interactive_numbered,
        interactive_prompt,
    )
    from urika.core.secrets import save_secret

    notif = settings.get("notifications", {})

    click.echo("\n  Notification setup\n")

    # Show current state
    email_cfg = notif.get("email", {})
    slack_cfg = notif.get("slack", {})
    telegram_cfg = notif.get("telegram", {})

    click.echo("  Current channels:")
    if email_cfg.get("to"):
        to_list = email_cfg["to"]
        if isinstance(to_list, list):
            to_list = ", ".join(to_list)
        click.echo(
            f"    Email:    {email_cfg.get('from_addr', '?')} -> {to_list} (configured)"
        )
    else:
        click.echo("    Email:    not configured")

    if slack_cfg.get("channel"):
        click.echo(f"    Slack:    {slack_cfg['channel']} (configured)")
    else:
        click.echo("    Slack:    not configured")

    if telegram_cfg.get("chat_id"):
        click.echo(f"    Telegram: chat {telegram_cfg['chat_id']} (configured)")
    else:
        click.echo("    Telegram: not configured")

    click.echo()

    while True:
        choice = interactive_numbered(
            "  Configure:",
            [
                "Email",
                "Slack",
                "Telegram",
                "Send test notification",
                "Disable all",
                "Done",
            ],
            default=6,
            allow_cancel=False,
        )

        if choice == "Done":
            break

        if choice == "Disable all":
            settings.setdefault("notifications", {})["enabled"] = False
            _save_notification_settings(settings, False, project_path)
            print_success("Notifications disabled.")
            break

        if choice == "Send test notification":
            _send_test_notification(settings.get("notifications", {}))
            continue

        if choice == "Email":
            click.echo("\n  Email setup\n")

            smtp_server = interactive_prompt(
                "SMTP server",
                default=email_cfg.get("smtp_server", "smtp.gmail.com"),
            )
            smtp_port = interactive_prompt(
                "SMTP port",
                default=str(email_cfg.get("smtp_port", 587)),
            )
            from_addr = interactive_prompt(
                "From address",
                default=email_cfg.get("from_addr", ""),
            )
            to_raw = interactive_prompt(
                "To addresses (comma-separated)",
                default=", ".join(email_cfg.get("to", [])),
            )
            to_addrs = [a.strip() for a in to_raw.split(",") if a.strip()]

            # App password / SMTP password (shown — these are generated tokens, not personal passwords)
            password = interactive_prompt(
                "App password (e.g. Gmail app password)",
                default="",
            )

            if password:
                save_secret("URIKA_EMAIL_PASSWORD", password)
                click.echo("  Saved! Password stored in ~/.urika/secrets.env")

            notif.setdefault("email", {}).update(
                {
                    "smtp_server": smtp_server,
                    "smtp_port": int(smtp_port),
                    "from_addr": from_addr,
                    "username": from_addr,
                    "to": to_addrs,
                    "password_env": "URIKA_EMAIL_PASSWORD",
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)
            print_success("Email configured.")

            if interactive_confirm("Send test email?", default=True):
                _send_test_notification(settings.get("notifications", {}))

            click.echo()
            continue

        if choice == "Slack":
            click.echo("\n  Slack setup\n")

            channel = interactive_prompt(
                "Channel (e.g. #urika-results)",
                default=slack_cfg.get("channel", ""),
            )

            bot_token = interactive_prompt(
                "Bot token (from Slack app settings)",
                default="",
            )

            if bot_token:
                save_secret("SLACK_BOT_TOKEN", bot_token)

            app_token = interactive_prompt(
                "App token (for interactive buttons, optional)",
                default="",
            )

            if app_token:
                save_secret("SLACK_APP_TOKEN", app_token)

            notif.setdefault("slack", {}).update(
                {
                    "channel": channel,
                    "bot_token_env": "SLACK_BOT_TOKEN",
                    "app_token_env": "SLACK_APP_TOKEN" if app_token else "",
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)

            tokens_saved = []
            if bot_token:
                tokens_saved.append("bot token")
            if app_token:
                tokens_saved.append("app token")
            if tokens_saved:
                click.echo(
                    f"  Saved! {', '.join(tokens_saved).capitalize()}"
                    " stored in ~/.urika/secrets.env"
                )
            print_success("Slack configured.")
            click.echo()
            continue

        if choice == "Telegram":
            click.echo("\n  Telegram setup\n")

            chat_id = interactive_prompt(
                "Chat ID (e.g. -100123456789)",
                default=str(telegram_cfg.get("chat_id", "")),
            )

            bot_token = interactive_prompt(
                "Bot token (from @BotFather)",
                default="",
            )

            if bot_token:
                save_secret("TELEGRAM_BOT_TOKEN", bot_token)
                click.echo("  Saved! Token stored in ~/.urika/secrets.env")

            notif.setdefault("telegram", {}).update(
                {
                    "chat_id": chat_id,
                    "bot_token_env": "TELEGRAM_BOT_TOKEN",
                }
            )
            settings["notifications"] = notif
            _save_notification_settings(settings, False, project_path)
            print_success("Telegram configured.")
            click.echo()
            continue


def _save_notification_settings(settings, is_project, project_path):
    """Save settings back to the appropriate TOML file."""
    if is_project:
        from urika.core.workspace import _write_toml

        _write_toml(project_path / "urika.toml", settings)
    else:
        from urika.core.settings import save_settings

        save_settings(settings)


@cli.command("setup")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def setup_command(json_output: bool) -> None:
    """Check installation and install optional packages."""
    from urika.cli_display import (
        print_error,
        print_step,
        print_success,
        print_warning,
    )

    if json_output:
        # Collect package status and hardware info as JSON
        _all_packages = {
            "numpy": "numpy",
            "pandas": "pandas",
            "scipy": "scipy",
            "scikit-learn": "sklearn",
            "statsmodels": "statsmodels",
            "pingouin": "pingouin",
            "click": "click",
            "claude-agent-sdk": "claude_agent_sdk",
            "matplotlib": "matplotlib",
            "seaborn": "seaborn",
            "xgboost": "xgboost",
            "lightgbm": "lightgbm",
            "optuna": "optuna",
            "shap": "shap",
            "imbalanced-learn": "imblearn",
            "pypdf": "pypdf",
            "torch": "torch",
            "transformers": "transformers",
            "torchvision": "torchvision",
            "torchaudio": "torchaudio",
        }
        pkg_status = {}
        for name, imp in _all_packages.items():
            try:
                __import__(imp)
                pkg_status[name] = True
            except Exception:
                pkg_status[name] = False

        hw_data: dict = {}
        try:
            from urika.core.hardware import detect_hardware as _dh

            hw_data = dict(_dh())
        except Exception:
            pass

        from urika.cli_helpers import output_json

        output_json(
            {
                "packages": pkg_status,
                "hardware": hw_data,
                "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            }
        )
        return

    click.echo()
    click.echo("  Urika Setup")
    click.echo("  " + "─" * 40)
    click.echo()

    # Check core packages
    core_packages = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scipy": "scipy",
        "scikit-learn": "sklearn",
        "statsmodels": "statsmodels",
        "pingouin": "pingouin",
        "click": "click",
        "claude-agent-sdk": "claude_agent_sdk",
    }
    print_step("Core packages:")
    all_core = True
    for name, imp in core_packages.items():
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")
            all_core = False
    if not all_core:
        print_warning("Some core packages missing. Run: pip install -e .")
        click.echo()

    # Check viz
    print_step("Visualization:")
    for name, imp in [
        ("matplotlib", "matplotlib"),
        ("seaborn", "seaborn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check ML
    print_step("Machine Learning:")
    for name, imp in [
        ("xgboost", "xgboost"),
        ("lightgbm", "lightgbm"),
        ("optuna", "optuna"),
        ("shap", "shap"),
        ("imbalanced-learn", "imblearn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check knowledge
    print_step("Knowledge pipeline:")
    try:
        __import__("pypdf")
        print_success("  pypdf")
    except ImportError:
        print_error("  pypdf — NOT INSTALLED")

    # Check DL
    print_step("Deep Learning:")
    dl_installed = True
    for name, imp in [
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("torchvision", "torchvision"),
        ("torchaudio", "torchaudio"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — not installed")
            dl_installed = False
        except Exception as exc:
            # RuntimeError from CUDA version mismatches, etc.
            short = str(exc).split(".")[0]
            print_error(f"  {name} — {short}")
            dl_installed = False

    # Check hardware
    click.echo()
    print_step("Hardware:")
    try:
        from urika.core.hardware import detect_hardware

        hw = detect_hardware()
        cpu = hw["cpu_count"]
        ram = hw["ram_gb"]
        print_success(f"  CPU: {cpu} cores")
        if ram:
            print_success(f"  RAM: {ram} GB")
        if hw["gpu"]:
            gpu = hw["gpu_name"]
            vram = hw.get("gpu_vram", "")
            label = f"  GPU: {gpu}"
            if vram:
                label += f" ({vram})"
            print_success(label)
        else:
            print_step("  GPU: none detected")
    except Exception:
        print_step("  Could not detect hardware")

    # Offer DL install
    if not dl_installed:
        click.echo()
        click.echo("  " + "─" * 40)
        click.echo()
        print_step("Deep learning packages are not installed.")
        print_step(
            "These are large (~2 GB) and only needed for neural network experiments."
        )
        click.echo()
        choice = click.prompt(
            "  Install deep learning packages?",
            type=click.Choice(
                ["yes", "no", "gpu", "cpu"],
                case_sensitive=False,
            ),
            default="no",
        )
        if choice == "no":
            click.echo("  Skipped.")
        else:
            import subprocess
            import sys

            def _torch_install_args(*, want_gpu: bool = True) -> tuple[list[str], str]:
                """Build pip install args for PyTorch based on platform.

                Returns (args_list, description_string).

                - macOS: default PyPI (includes MPS for Apple Silicon)
                - ARM (any OS without NVIDIA): default PyPI
                - x86 + NVIDIA: detect CUDA version, use matching wheel
                - No GPU / want_gpu=False: CPU-only wheels (x86) or default (ARM)
                """
                import platform

                # Use --force-reinstall if torchaudio has a CUDA mismatch
                force = False
                try:
                    r = subprocess.run(
                        [sys.executable, "-c", "import torchaudio"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.returncode != 0 and "CUDA version" in r.stderr:
                        force = True
                except Exception:
                    pass

                base = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *(["--force-reinstall"] if force else []),
                    "torch",
                    "torchvision",
                    "torchaudio",
                ]
                arch = platform.machine().lower()
                is_arm = arch in ("arm64", "aarch64", "armv8l")

                # macOS — default PyPI includes MPS for Apple Silicon
                if sys.platform == "darwin":
                    desc = "MPS" if is_arm else "CPU"
                    return base, desc

                # ARM Linux/Windows — no CUDA index, default PyPI
                if is_arm:
                    cuda_tag = _detect_cuda_tag() if want_gpu else None
                    if cuda_tag:
                        # ARM + NVIDIA (Jetson) — use default pip, torch auto-detects
                        return base, f"ARM + CUDA ({cuda_tag})"
                    return base, "ARM CPU"

                # x86 Linux/Windows
                if want_gpu:
                    cuda_tag = _detect_cuda_tag()
                    if cuda_tag:
                        return (
                            base
                            + [
                                "--index-url",
                                f"https://download.pytorch.org/whl/{cuda_tag}",
                            ],
                            f"CUDA {cuda_tag}",
                        )
                return (
                    base + ["--index-url", "https://download.pytorch.org/whl/cpu"],
                    "CPU",
                )

            def _detect_cuda_tag() -> str | None:
                """Detect CUDA version, return wheel tag (e.g. 'cu124') or None."""
                # 1. Check existing torch installation
                try:
                    import torch

                    cv = torch.version.cuda
                    if cv:
                        parts = cv.split(".")
                        return f"cu{parts[0]}{parts[1]}"
                except Exception:
                    pass
                # 2. Check nvcc
                try:
                    import re

                    r = subprocess.run(
                        ["nvcc", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        m = re.search(r"release (\d+)\.(\d+)", r.stdout)
                        if m:
                            return f"cu{m.group(1)}{m.group(2)}"
                except Exception:
                    pass
                # 3. Check nvidia-smi exists (GPU present but no toolkit)
                try:
                    r = subprocess.run(
                        ["nvidia-smi"],
                        capture_output=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        return "cu124"  # Default to latest stable
                except Exception:
                    pass
                return None

            if choice == "gpu":
                args, desc = _torch_install_args(want_gpu=True)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                # Then the rest
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            elif choice == "cpu":
                args, desc = _torch_install_args(want_gpu=False)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            else:
                # "yes" — auto-detect
                try:
                    from urika.core.hardware import (
                        detect_hardware,
                    )

                    hw_info = detect_hardware()
                    has_gpu = hw_info.get("gpu", False)
                except Exception:
                    has_gpu = False

                args, desc = _torch_install_args(want_gpu=has_gpu)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            print_success("Deep learning packages installed.")
    else:
        # Check GPU availability with torch
        click.echo()
        try:
            import torch

            if torch.cuda.is_available():
                dev = torch.cuda.get_device_name(0)
                print_success(f"  PyTorch CUDA: {dev}")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                print_success("  PyTorch MPS: available")
            else:
                print_step("  PyTorch: CPU only")
        except Exception:
            pass

    click.echo()
    print_step("Claude access:")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print_success("  ANTHROPIC_API_KEY is set")
    else:
        print_warning(
            "  ANTHROPIC_API_KEY not set — needed unless using Claude Max/Pro"
        )

    click.echo()
    # Check for updates
    print_step("Updates:")
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates(force=True)
        if update_info:
            msg = format_update_message(update_info)
            print_warning(f"  {msg}")
        else:
            print_success("  You are on the latest version")
    except Exception:
        print_step("  Could not check for updates")

    click.echo()
    print_success("Setup check complete.")
    click.echo()


@cli.group("venv")
def venv_group() -> None:
    """Manage project virtual environments."""


@venv_group.command("create")
@click.argument("project", required=False, default=None)
def venv_create(project: str | None) -> None:
    """Create a venv for a project."""
    import tomllib

    from urika.core.venv import create_project_venv

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    venv_path = create_project_venv(project_path)

    # Update urika.toml to enable venv
    toml_path = project_path / "urika.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    data.setdefault("environment", {})["venv"] = True
    from urika.core.workspace import _write_toml

    _write_toml(toml_path, data)

    click.echo(f"Created .venv at {venv_path}")


@venv_group.command("status")
@click.argument("project", required=False, default=None)
def venv_status(project: str | None) -> None:
    """Show venv status for a project."""
    from urika.core.venv import is_venv_enabled

    project = _ensure_project(project)
    project_path, _config = _resolve_project(project)

    if is_venv_enabled(project_path):
        venv_path = project_path / ".venv"
        exists = venv_path.exists()
        click.echo(f"Venv: enabled ({'exists' if exists else 'NOT FOUND'})")
        click.echo(f"Path: {venv_path}")
    else:
        click.echo("Venv: not enabled (using global environment)")
