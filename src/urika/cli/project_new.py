"""`urika new` command + interactive builder loop + knowledge ingestion.

Split out of cli/project.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``new``.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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
@click.option(
    "--privacy-mode",
    "privacy_mode_flag",
    default=None,
    type=click.Choice(["open", "private", "hybrid"]),
    help=(
        "Data privacy mode (open/private/hybrid). In --json mode this is "
        "the only way to pick non-open; private/hybrid additionally "
        "require a configured private endpoint in global settings."
    ),
)
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help=(
        "Overwrite an existing project of the same name (destructive). "
        "Required in --json mode if the project directory already exists; "
        "the interactive flow always confirms first."
    ),
)
def new(
    name: str | None,
    question: str | None,
    mode: str | None,
    data_path: str | None,
    description: str | None,
    privacy_mode_flag: str | None = None,
    json_output: bool = False,
    overwrite: bool = False,
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

    # Load saved endpoints from ~/.urika/settings.toml. There is NO
    # saved default mode — each project picks its mode fresh. v0.4:
    # walk every named endpoint (not just the literal "private" key)
    # so users can pick from a multi-endpoint setup
    # (private-vllm-large, private-vllm-small, etc.) without retyping
    # URLs.
    from urika.core.settings import get_named_endpoints

    _named_endpoints = [
        ep for ep in get_named_endpoints() if (ep.get("base_url") or "").strip()
    ]
    # Legacy fallback: pre-v0.4 only the literal "private" key was
    # consulted. Keep that as the single-endpoint default URL so the
    # JSON-mode fallback works unchanged when there's exactly one
    # endpoint named "private".
    _saved_url = ""
    _saved_key_env = ""
    for _ep in _named_endpoints:
        if _ep.get("name") == "private":
            _saved_url = (_ep.get("base_url") or "").strip()
            _saved_key_env = (_ep.get("api_key_env") or "").strip()
            break
    if not _saved_url and _named_endpoints:
        # Single configured endpoint → use it as the JSON-mode default.
        _saved_url = (_named_endpoints[0].get("base_url") or "").strip()
        _saved_key_env = (_named_endpoints[0].get("api_key_env") or "").strip()

    # In JSON mode, skip all interactive prompts. The default privacy
    # mode is ``open`` (cloud); the user may opt into private/hybrid via
    # --privacy-mode, in which case we must have a configured private
    # endpoint in globals or we abort here rather than letting the
    # runtime fail at first agent run (post-Commit 1).
    if json_output:
        privacy_mode_val = privacy_mode_flag or "open"
        if privacy_mode_val in ("private", "hybrid"):
            saved_url_str = (_saved_url or "").strip()
            if not saved_url_str:
                from urika.cli_helpers import output_json_error

                output_json_error(
                    f"Privacy mode '{privacy_mode_val}' requires a "
                    f"configured private endpoint, but no "
                    f"[privacy.endpoints.private].base_url is set in "
                    f"global settings. Run `urika config` (or use the "
                    f"dashboard's Privacy tab) before creating a "
                    f"private/hybrid project in --json mode."
                )
                raise SystemExit(1)
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
        # Privacy mode — ask FIRST, before data path. No pre-fill: each
        # project picks its own mode regardless of any global config.
        privacy_choice = _prompt_numbered(
            "\nData privacy mode:",
            [
                "Open — agents use cloud models, no restrictions",
                "Private — all agents use private/local endpoints only",
                "Hybrid — data reading is private, thinking uses cloud models",
            ],
            default=1,
        )
        _privacy_map = {"Open": "open", "Private": "private", "Hybrid": "hybrid"}
        privacy_mode_val = _privacy_map.get(
            privacy_choice.split(" —")[0].strip(), "open"
        )

        private_endpoint_url = ""
        private_endpoint_key_env = ""
        if privacy_mode_val in ("private", "hybrid"):
            # v0.4: when global endpoints exist, present a numbered
            # menu so users with a multi-endpoint setup
            # (private-vllm-large, private-vllm-small, …) can pick
            # one without retyping URLs. Last option is always
            # "Configure a new endpoint" which falls through to the
            # legacy URL prompt.
            if _named_endpoints:
                click.echo("\n  Configured private endpoints:")
                _ep_options = []
                for ep in _named_endpoints:
                    label = (
                        f"{ep['name']}  ({ep['base_url']}"
                        + (
                            f", key={ep['api_key_env']}"
                            if ep.get("api_key_env")
                            else ""
                        )
                        + ")"
                    )
                    _ep_options.append(label)
                _ep_options.append("Configure a new endpoint")
                ep_choice = _prompt_numbered(
                    "  Use which endpoint?",
                    _ep_options,
                    default=1,
                )
                if not ep_choice.startswith("Configure a new"):
                    # User picked an existing endpoint by name.
                    chosen_name = ep_choice.split("  (", 1)[0].strip()
                    chosen_ep = next(
                        (e for e in _named_endpoints if e["name"] == chosen_name),
                        None,
                    )
                    if chosen_ep is not None:
                        private_endpoint_url = (chosen_ep.get("base_url") or "").strip()
                        private_endpoint_key_env = (
                            chosen_ep.get("api_key_env") or ""
                        ).strip()
                        print_step("Testing endpoint connection…")
                        if _test_endpoint(private_endpoint_url):
                            print_success(f"Connected to {private_endpoint_url}")
                        else:
                            print_error(
                                f"Could not connect to "
                                f"{private_endpoint_url} — proceeding "
                                f"anyway; you can fix the endpoint "
                                f"on the dashboard's Privacy tab."
                            )
            # When the user picked "Configure a new endpoint" or no
            # global endpoints existed, fall through to the legacy
            # URL prompt loop.
            if not private_endpoint_url:
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
                        required=True,
                    )
                    # Defensive — if interactive_prompt somehow returned
                    # an empty string (e.g. EOF on piped stdin with no
                    # default), don't proceed with a blank base_url.
                    if not (private_endpoint_url or "").strip():
                        print_error(
                            "Private endpoint URL is required for "
                            f"{privacy_mode_val} mode."
                        )
                        raise click.Abort()
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
        # JSON mode: refuse to clobber unless --overwrite is explicit.
        # Pre-v0.4.2 this silently rmtree'd any existing project (C4),
        # which destroyed scripted-create users' work without warning.
        if (project_dir / "urika.toml").exists():
            if not overwrite:
                from urika.cli_helpers import output_json_error

                output_json_error(
                    f"Project '{name}' already exists at {project_dir}. "
                    f"Pass --overwrite to replace it (this is destructive: "
                    f"the existing project directory will be deleted)."
                )
                raise SystemExit(1)
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
        print_success(f"Notifications auto-enabled: {', '.join(seeded_channels)}")

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
    # The loop asks clarifying questions and waits for user input. It
    # has no value — and no possible answer source — when stdin is not
    # a TTY (CliRunner tests, ``urika new ... < /dev/null``, CI
    # scripts). Pre-v0.4.0 this guard was missing, so every
    # CliRunner-based unit test of ``urika new`` silently spawned a
    # real Anthropic API agent loop and burned credits until something
    # killed it. Also honour ``URIKA_NO_BUILDER_AGENT=1`` as an
    # explicit opt-out for non-CliRunner scripted callers.
    import sys as _sys

    _no_builder_env = bool(os.environ.get("URIKA_NO_BUILDER_AGENT"))
    _stdin_is_tty = bool(getattr(_sys.stdin, "isatty", lambda: False)())
    if not _no_builder_env and _stdin_is_tty:
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
            print_error(
                f"Agent loop unavailable ({exc}). Continuing with manual setup."
            )
    elif _no_builder_env:
        click.echo("  Skipping project-builder agent (URIKA_NO_BUILDER_AGENT set).")

    registry = ProjectRegistry()
    registry.register(name, project_dir)

    print_success(f"Created project '{name}' at {project_dir}")

    # The post-creation "offer to run an experiment" block prompts via
    # ``_prompt_numbered`` whose default is "Run one experiment", which
    # under non-TTY stdin (CliRunner, CI) silently dispatches to
    # ``urika run`` and spawns the orchestrator's planning_agent +
    # task_agent against the live API. Skip the entire block when
    # there's nobody to answer the prompt OR when the caller opted
    # out via env. Same guards as the project-builder loop above.
    if _no_builder_env or not _stdin_is_tty:
        return

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
    """CLI entry point for the interactive builder loop.

    Thin sync wrapper around ``urika.core.builder_loop.run_builder_loop``
    that injects CLI-shaped ``ask_user`` (prompt_toolkit / numbered
    menu) and ``emit`` (ThinkingPanel + print_* helpers) callbacks so
    the runtime-agnostic core behaves identically to the pre-v0.4.5
    in-line implementation.

    v0.4.5 Track 1 refactor: the loop body moved to
    ``urika.core.builder_loop`` so the dashboard's new-project wizard
    can drive the same core via SSE + POST-answer endpoints. CLI
    behaviour is unchanged — same agent prompts, same on-disk
    artifacts, same screen output.
    """
    import asyncio

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
    from urika.core.builder_loop import (
        BuilderAborted,
        BuilderEvent,
        BuilderQuestion,
        run_builder_loop,
    )

    # CLI-side state for the emit handler: a persistent footer panel
    # for the whole loop, plus a Spinner that wraps each refinement-
    # phase agent call. Pre-v0.4.5 the panel + spinner were created
    # inline in the loop body; the refactor pushed UI concerns out so
    # the dashboard can run a queue-driven loop with no terminal UI.
    panel = ThinkingPanel()
    panel.project = getattr(builder, "name", "")
    panel.activity = thinking_phrase()
    panel.activate()
    panel.start_spinner()

    # Used for the "spinner around refinement-phase agent calls"
    # affordance — see the ``Spinner`` block at the bottom of the
    # original pre-v0.4.5 function.
    active_spinner: list[Spinner] = []

    def _emit(event: BuilderEvent) -> None:
        kind = event.kind
        p = event.payload
        if kind == "step":
            print_step(p.get("text", ""))
        elif kind == "phase":
            agent = p.get("agent", "")
            activity = p.get("activity", _AGENT_ACTIVITY.get(agent, thinking_phrase()))
            print_agent(agent)
            panel.update(agent=agent, activity=activity)
            # Refinement-phase agent calls were wrapped in a Spinner
            # pre-refactor. Mirror that here by opening a Spinner on
            # phase change for the advisor/planning refinement loops
            # and closing it on the next phase / agent_text / done.
            for s in active_spinner:
                try:
                    s.__exit__(None, None, None)
                except Exception:
                    pass
            active_spinner.clear()
        elif kind == "model":
            panel.set_model(p.get("model", ""))
        elif kind == "tool_use":
            print_tool_use(p.get("tool", ""), p.get("detail", ""))
            panel.set_thinking(p.get("tool", ""))
        elif kind == "thinking":
            panel.set_thinking(p.get("phrase", "Thinking…"))
        elif kind == "error":
            print_error(p.get("message", ""))
        elif kind == "agent_text":
            click.echo(format_agent_output(p.get("text", "")))
        elif kind == "done":
            # Panel cleanup happens in the wrapper's ``finally`` —
            # done-event is informational.
            pass

    async def _ask(q: BuilderQuestion) -> str:
        """CLI ask_user: numbered menu for ``options``, plain prompt
        otherwise. Runs the (sync) prompt_toolkit primitives via
        ``asyncio.to_thread`` so we don't block the event loop."""
        if q.options and q.is_terminal_choice:
            # Terminal "looks good / refine / abort" decision row.
            return await asyncio.to_thread(_prompt_numbered, q.text, q.options, 1)
        if q.options:
            # Non-terminal multi-choice clarifying question — render
            # the options inline (matching the pre-refactor output),
            # then accept a free-text answer so the user can either
            # type "1" / "2" or write something custom.
            click.echo(f"\n{q.text}")
            for j, opt in enumerate(q.options, 1):
                click.echo(f"  {j}. {opt}")
            return await asyncio.to_thread(
                interactive_prompt, "Your answer (or 'done' to move on)"
            )
        if q.text:
            click.echo(f"\n{q.text}")
        return await asyncio.to_thread(
            interactive_prompt, "Your answer (or 'done' to move on)"
        )

    try:
        asyncio.run(
            run_builder_loop(
                builder,
                scan_result,
                data_summary,
                description,
                question,
                ask_user=_ask,
                emit=_emit,
                extra_profiles=extra_profiles,
            )
        )
    except BuilderAborted:
        raise click.ClickException("Aborted.")
    finally:
        for s in active_spinner:
            try:
                s.__exit__(None, None, None)
            except Exception:
                pass
        panel.cleanup()


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
