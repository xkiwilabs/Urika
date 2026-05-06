"""Agent-related REPL commands: /advisor, /evaluate, /plan, /report, /present, /finalize, /build-tool."""

from __future__ import annotations

import click

from urika.cli_display import _C
from urika.repl.session import ReplSession
from urika.repl.helpers import (
    _pick_experiment,
    _run_single_agent,
    _save_presentation,
    _get_audience,
    _file_link,
)


def cmd_advisor(session: ReplSession, args: str) -> None:
    """Ask the advisor agent a question.

    v0.4.2 Package I: pre-fix this delegated to ``_handle_free_text``
    which runs ``OrchestratorChat`` — a *different* agent with a
    different system prompt and no access to ``advisor_memory``. So
    typing ``/advisor <q>`` invoked the orchestrator silently,
    ignoring the user's explicit choice. The CLI ``urika advisor``
    has always run the actual ``advisor_agent`` role; the slash now
    matches.
    """
    text = args.strip()
    if not text:
        click.echo("  Usage: /advisor <question or instructions>")
        return

    # Pull advisor history into the prompt so the agent has continuity
    # across slash invocations within the same project — mirrors what
    # ``cli/agents.py::advisor`` does on the shell side.
    try:
        from urika.core.advisor_memory import (
            append_exchange,
            format_recent_history,
            load_history,
        )

        recent = format_recent_history(load_history(session.project_path, last_n=6))
        prompt = (
            f"Recent advisor conversation:\n\n{recent}\n\n---\n\n"
            f"User question: {text}"
            if recent
            else text
        )
    except Exception:
        prompt = text
        append_exchange = None  # type: ignore[assignment]

    click.echo("  Running advisor agent...")
    session.set_agent_active("advisor")
    try:
        # Advisor is a project-level agent (no specific experiment),
        # but ``_run_single_agent`` requires an experiment_id arg. We
        # use the most recent experiment (or empty string when there
        # are none yet) so the helper's signature is satisfied — the
        # advisor's prompt doesn't depend on the experiment id.
        try:
            from urika.core.experiment import list_experiments

            exps = list_experiments(session.project_path)
            exp_id = exps[-1].experiment_id if exps else ""
        except Exception:
            exp_id = ""

        result = _run_single_agent(session, "advisor_agent", exp_id, prompt)

        # Persist the exchange to advisor_memory so the next /advisor
        # call (or shell ``urika advisor``) has the same continuity.
        if append_exchange is not None and result is not None:
            try:
                response_text = (
                    result.get("response", "") or result.get("text", "") or ""
                )
                append_exchange(
                    session.project_path,
                    role="user",
                    text=text,
                    source="repl",
                )
                append_exchange(
                    session.project_path,
                    role="advisor",
                    text=response_text,
                    source="repl",
                )

                # Parse advisor suggestions and stash them on the
                # session — same flow as the orchestrator chat path
                # (Package H + earlier Package I item 1).
                from urika.orchestrator.parsing import parse_suggestions

                parsed = parse_suggestions(response_text)
                if parsed and parsed.get("suggestions"):
                    session.pending_suggestions = parsed["suggestions"]
                    n = len(session.pending_suggestions)
                    click.echo(
                        f"  ✨ {n} experiment suggestion(s) captured. "
                        f"Type /run to start."
                    )
            except Exception:
                # Memory + suggestion side-effects are best-effort.
                pass
    finally:
        session.set_agent_idle()


def cmd_evaluate(session: ReplSession, args: str) -> None:
    """Run evaluator on an experiment."""
    exp_id = args.strip()
    if not exp_id:
        from urika.core.experiment import list_experiments

        experiments = list_experiments(session.project_path)
        if not experiments:
            click.echo("  No experiments.")
            return
        exp_id = experiments[-1].experiment_id

    click.echo(f"  Running evaluator on {exp_id}...")
    session.set_agent_active("evaluate")
    try:
        _run_single_agent(
            session, "evaluator", exp_id, f"Evaluate experiment {exp_id}."
        )
    finally:
        session.set_agent_idle()


def cmd_plan(session: ReplSession, args: str) -> None:
    """Run planning agent to design a method."""
    exp_id = args.strip()
    if not exp_id:
        from urika.core.experiment import list_experiments

        experiments = list_experiments(session.project_path)
        if not experiments:
            click.echo("  No experiments.")
            return
        exp_id = experiments[-1].experiment_id

    context = "Design the next method based on current results."
    if session.conversation:
        context = session.get_conversation_context() + "\n\n" + context

    click.echo(f"  Running planning agent for {exp_id}...")
    session.set_agent_active("plan")
    try:
        _run_single_agent(session, "planning_agent", exp_id, context)
    finally:
        session.set_agent_idle()


def cmd_report(session: ReplSession, args: str) -> None:
    """Generate reports."""
    exp_choice = _pick_experiment(session, args, allow_all=True)
    if exp_choice is None:
        return

    from urika.core.labbook import (
        generate_experiment_summary,
        generate_key_findings,
        generate_results_summary,
        update_experiment_notes,
    )
    from urika.core.readme_generator import write_readme

    audience = _get_audience(session)
    session.set_agent_active("report")
    try:
        if exp_choice == "all":
            # Generate reports for each experiment
            click.echo(
                f"  {_C.BLUE}Generating reports for all experiments...{_C.RESET}"
            )
            from urika.core.experiment import list_experiments

            for exp in list_experiments(session.project_path):
                click.echo(f"  {_C.BLUE}Processing {exp.experiment_id}...{_C.RESET}")
                try:
                    update_experiment_notes(session.project_path, exp.experiment_id)
                    generate_experiment_summary(session.project_path, exp.experiment_id)
                except Exception:
                    pass
                text = _run_single_agent(
                    session,
                    "report_agent",
                    exp.experiment_id,
                    f"Write a detailed narrative report for experiment {exp.experiment_id}.",
                    audience=audience,
                )
                if text:
                    from urika.core.report_writer import write_versioned

                    narrative_path = (
                        session.project_path
                        / "experiments"
                        / exp.experiment_id
                        / "labbook"
                        / "narrative.md"
                    )
                    narrative_path.parent.mkdir(parents=True, exist_ok=True)
                    write_versioned(narrative_path, text + "\n")
            click.echo("  \u2713 All experiment reports updated")
        elif exp_choice == "project":
            # Project-level reports
            click.echo(f"  {_C.BLUE}Generating project-level reports...{_C.RESET}")
            try:
                generate_results_summary(session.project_path)
                generate_key_findings(session.project_path)
                write_readme(session.project_path)
            except Exception:
                pass

            text = _run_single_agent(
                session,
                "report_agent",
                "",
                "Write a project-level narrative report covering all experiments and the research progression.",
                audience=audience,
            )
            if text:
                from urika.core.report_writer import write_versioned

                narrative_path = session.project_path / "projectbook" / "narrative.md"
                narrative_path.parent.mkdir(parents=True, exist_ok=True)
                write_versioned(narrative_path, text + "\n")
                link = _file_link(narrative_path, "projectbook/narrative.md")
                click.echo(f"  \u2713 Project narrative: {link}")
                readme_link = _file_link(
                    session.project_path / "README.md", "README.md"
                )
                click.echo(f"  \u2713 README: {readme_link}")
        else:
            click.echo(f"  {_C.BLUE}Generating report for {exp_choice}...{_C.RESET}")
            try:
                update_experiment_notes(session.project_path, exp_choice)
                generate_experiment_summary(session.project_path, exp_choice)
                summary_path = (
                    session.project_path
                    / "experiments"
                    / exp_choice
                    / "labbook"
                    / "summary.md"
                )
                link = _file_link(
                    summary_path, f"experiments/{exp_choice}/labbook/summary.md"
                )
                click.echo(f"  \u2713 Report: {link}")
            except Exception as exc:
                click.echo(f"  \u2717 Error: {exc}")

            # Generate experiment narrative via report agent
            text = _run_single_agent(
                session,
                "report_agent",
                exp_choice,
                f"Write a detailed narrative report for experiment {exp_choice}.",
                audience=audience,
            )
            if text:
                from urika.core.report_writer import write_versioned

                narrative_path = (
                    session.project_path
                    / "experiments"
                    / exp_choice
                    / "labbook"
                    / "narrative.md"
                )
                narrative_path.parent.mkdir(parents=True, exist_ok=True)
                write_versioned(narrative_path, text + "\n")
                link = _file_link(
                    narrative_path,
                    f"experiments/{exp_choice}/labbook/narrative.md",
                )
                click.echo(f"  \u2713 Narrative: {link}")
    finally:
        session.set_agent_idle()


def cmd_present(session: ReplSession, args: str) -> None:
    """Generate presentation for an experiment."""
    exp_choice = _pick_experiment(session, args, allow_all=True)
    if exp_choice is None:
        return

    audience = _get_audience(session)
    session.set_agent_active("present")
    try:
        if exp_choice == "all":
            # Generate presentation for each experiment
            from urika.core.experiment import list_experiments

            experiments = list_experiments(session.project_path)
            for exp in experiments:
                click.echo(
                    f"  {_C.BLUE}Generating presentation for {exp.experiment_id}...{_C.RESET}"
                )
                text = _run_single_agent(
                    session,
                    "presentation_agent",
                    exp.experiment_id,
                    f"Create a presentation for experiment {exp.experiment_id}.",
                    audience=audience,
                )
                if text:
                    _save_presentation(session, text, exp.experiment_id)
            click.echo("  \u2713 All presentations generated")
        elif exp_choice == "project":
            # One project-level presentation covering everything
            click.echo(f"  {_C.BLUE}Generating project-level presentation...{_C.RESET}")
            text = _run_single_agent(
                session,
                "presentation_agent",
                "",
                "Create a project-level presentation covering ALL experiments, "
                "the research progression, key findings across the entire project, "
                "and next steps. This is an overview presentation, not per-experiment.",
                audience=audience,
            )
            if text:
                _save_presentation(session, text, None)
        else:
            # Single experiment presentation
            text = _run_single_agent(
                session,
                "presentation_agent",
                exp_choice,
                f"Create a presentation for experiment {exp_choice}.",
                audience=audience,
            )
            if text:
                _save_presentation(session, text, exp_choice)
    finally:
        session.set_agent_idle()


def cmd_finalize(session: ReplSession, args: str) -> None:
    """Finalize project -- methods, report, presentation."""
    import os

    raw = args.strip()
    draft = False
    if "--draft" in raw:
        draft = True
        raw = raw.replace("--draft", "").strip()
    instructions = raw
    audience = _get_audience(session)
    os.environ["URIKA_REPL"] = "1"
    session.set_agent_active("finalize")
    try:
        from urika.cli import finalize as cli_finalize

        ctx = click.Context(cli_finalize)
        ctx.invoke(
            cli_finalize,
            project=session.project_name,
            instructions=instructions,
            audience=audience,
            draft=draft,
        )
    finally:
        session.set_agent_idle()
        os.environ.pop("URIKA_REPL", None)


def cmd_build_tool(session: ReplSession, args: str) -> None:
    """Build a custom tool for the project."""
    instructions = args.strip()
    if not instructions:
        click.echo(
            "  Usage: /build-tool <instructions>\n"
            "  Examples:\n"
            "    /build-tool create an EEG epoch extractor using MNE\n"
            "    /build-tool build a tool that computes ICC using pingouin\n"
            "    /build-tool install librosa and create an audio feature extractor"
        )
        return

    session.set_agent_active("build-tool")
    try:
        _run_single_agent(session, "tool_builder", "", instructions)
    finally:
        session.set_agent_idle()
