"""`urika new` command + interactive builder loop + knowledge ingestion.

Split out of cli/project.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``new``.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from urika.cli._base import cli
from urika.cli._helpers import (
    _projects_dir,
    _prompt_numbered,
    _prompt_path,
    _sanitize_project_name,
    _test_endpoint,
)
from urika.core.experiment import create_experiment
from urika.core.registry import ProjectRegistry


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
    name = _sanitize_project_name(name)

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
            name = _sanitize_project_name(name)
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
        # Seed notifications channels from global auto_enable flags so
        # JSON-mode projects match interactive ``urika new`` and the
        # dashboard's POST /api/projects.
        from urika.cli.config_notifications import (
            seed_project_notifications_from_global,
        )

        seed_project_notifications_from_global(project_dir)
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

    # Seed notifications channels from global auto_enable flags. No
    # interactive prompts here — the user configures auto_enable once
    # via 'urika notifications' and every subsequent project picks it
    # up. Mirrors the dashboard's POST /api/projects.
    from urika.cli.config_notifications import seed_project_notifications_from_global

    seeded_channels = seed_project_notifications_from_global(project_dir)
    if seeded_channels and not json_output:
        print_success(
            f"Notifications auto-enabled: {', '.join(seeded_channels)}"
        )

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

    # Lazy import to avoid circular dependency
    from urika.cli.run import run

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
        try:
            max_exp = int(interactive_prompt("How many experiments?", default="3"))
        except ValueError:
            max_exp = 3
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

    # Offer to open the dashboard (interactive only — never in --json mode
    # and never when stdout is not a TTY, e.g. inside CliRunner tests
    # or piped stdout).
    import sys

    if not json_output and sys.stdout.isatty() and sys.stdin.isatty():
        try:
            if interactive_confirm("Open the dashboard now?", default=True):
                import subprocess

                subprocess.Popen(
                    [sys.executable, "-m", "urika", "dashboard", name],
                    start_new_session=True,
                )
                click.echo("  Dashboard launching in a new browser tab...")
        except Exception:
            # Don't let dashboard prompt failures block project creation flow
            pass


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
