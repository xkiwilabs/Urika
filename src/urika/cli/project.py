"""Project-related CLI commands: new, list, status, update, inspect."""

from __future__ import annotations

import os
from pathlib import Path

import click

from urika.cli._legacy import cli
from urika.core.experiment import create_experiment, list_experiments
from urika.core.models import ProjectConfig
from urika.core.progress import load_progress
from urika.core.registry import ProjectRegistry
from urika.core.workspace import load_project_config

from urika.cli._helpers import (
    _make_on_message,
    _record_agent_usage,
    _sanitize_project_name,
    _projects_dir,
    _resolve_project,
    _ensure_project,
    _test_endpoint,
    _prompt_numbered,
    _prompt_path,
)


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

    # Lazy import to avoid circular dependency — run may be in _legacy or run.py
    from urika.cli._legacy import run

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
