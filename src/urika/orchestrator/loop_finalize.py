"""Post-experiment artifact generation for the orchestrator loop.

Split out of loop.py as part of Phase 8 refactoring. This module owns
the "after an experiment succeeds, produce the write-ups and the slide
deck" work:

    _generate_reports          — labbook + README + experiment/project narratives
    _generate_presentation     — reveal.js slide deck via the presentation agent
    _async_generate_summary    — short 2-3 sentence paragraph for the README

Each returns a usage dict (tokens_in, tokens_out, cost_usd,
agent_calls) so the caller can aggregate across the whole experiment.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from urika.agents.audience import format_audience_context
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentRunner
from urika.core.progress import load_progress

logger = logging.getLogger(__name__)


async def _generate_reports(
    project_dir: Path,
    experiment_id: str,
    progress: Callable[..., Any],
    runner: AgentRunner | None = None,
    on_message: Callable[..., Any] | None = None,
    audience: str = "expert",
) -> dict[str, int | float]:
    """Generate labbook reports and update README after experiment completion.

    Returns a dict with usage totals: tokens_in, tokens_out, cost_usd, agent_calls.
    """
    _usage: dict[str, int | float] = {
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "agent_calls": 0,
    }

    def _track(result: object) -> None:
        _usage["tokens_in"] += result.tokens_in
        _usage["tokens_out"] += result.tokens_out
        _usage["cost_usd"] += result.cost_usd or 0.0
        _usage["agent_calls"] += 1

    try:
        from urika.core.labbook import (
            generate_experiment_summary,
            generate_key_findings,
            generate_results_summary,
            update_experiment_notes,
        )

        progress("phase", "Generating reports")
        update_experiment_notes(project_dir, experiment_id)
        generate_experiment_summary(project_dir, experiment_id)
        generate_results_summary(project_dir)
        generate_key_findings(project_dir)
    except Exception as exc:
        logger.warning("Labbook generation failed: %s", exc)

    # Update project README.md with agent-written summary
    try:
        from urika.core.readme_generator import write_readme

        summary = ""
        if runner is not None:
            try:
                summary, summary_usage = await _async_generate_summary(
                    project_dir, experiment_id, runner, on_message
                )
                _usage["tokens_in"] += summary_usage.get("tokens_in", 0)
                _usage["tokens_out"] += summary_usage.get("tokens_out", 0)
                _usage["cost_usd"] += summary_usage.get("cost_usd", 0.0)
                _usage["agent_calls"] += summary_usage.get("agent_calls", 0)
            except Exception as exc:
                logger.warning("README summary generation failed: %s", exc)
        write_readme(project_dir, summary=summary)
        progress("result", "README.md updated")
    except Exception as exc:
        logger.warning("README update failed: %s", exc)

    # Generate agent-written experiment narrative
    if runner is not None:
        try:
            registry = AgentRegistry()
            registry.discover()
            report_role = registry.get("report_agent")
            if report_role is not None:
                progress("agent", "Report agent — writing experiment narrative")
                config = report_role.build_config(
                    project_dir=project_dir,
                    experiment_id=experiment_id,
                    audience=audience,
                )
                result = await runner.run(
                    config,
                    format_audience_context(audience)
                    + f"Write a detailed narrative report for experiment {experiment_id}.",
                    on_message=on_message,
                )
                _track(result)
                if result.success and result.text_output:
                    content = result.text_output.strip()
                    # Only write if the output looks like actual report content
                    # (has markdown headings and is substantial), not agent narration
                    if len(content) > 500 and content.count("\n#") >= 2:
                        from urika.core.report_writer import write_versioned

                        narrative_path = (
                            project_dir
                            / "experiments"
                            / experiment_id
                            / "labbook"
                            / "narrative.md"
                        )
                        narrative_path.parent.mkdir(parents=True, exist_ok=True)
                        write_versioned(narrative_path, content + "\n")
                        progress("result", "Experiment narrative written")
                    else:
                        progress("result", "Experiment narrative generated")
        except Exception as exc:
            logger.warning("Experiment narrative generation failed: %s", exc)

    # NOTE: the project-level narrative (projectbook/narrative.md) used
    # to be regenerated here after every successful experiment. That
    # was duplicate work — it summarised "all experiments and the
    # research progression" from scratch on each criteria-met event,
    # adding 10–25 minutes of cloud-LLM tail to every `urika run`.
    # The same narrative is now produced on demand by `urika report`
    # (cheaper prompt) and superseded at project end by
    # `urika finalize` (which writes projectbook/final-report.md from
    # the structured findings.json). Removed as part of v0.4.0 to
    # cut per-experiment wall-clock and stop the smoke-harness
    # SIGTERM-during-narrative false-positives.
    #
    # Agent feedback loop is unaffected — neither the planner nor the
    # advisor reads projectbook/narrative.md. Their cross-experiment
    # memory is methods.json + criteria.json + advisor-history.json +
    # advisor-context.md (rolling summary refreshed per advisor call)
    # + project memory.

    # Generate presentation slide deck
    if runner is not None:
        try:
            pres_usage = await _generate_presentation(
                project_dir, experiment_id, runner, progress, on_message,
                audience=audience,
            )
            _usage["tokens_in"] += pres_usage.get("tokens_in", 0)
            _usage["tokens_out"] += pres_usage.get("tokens_out", 0)
            _usage["cost_usd"] += pres_usage.get("cost_usd", 0.0)
            _usage["agent_calls"] += pres_usage.get("agent_calls", 0)
        except Exception as exc:
            logger.warning("Presentation generation failed: %s", exc)

    return _usage


async def _generate_presentation(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    progress: Callable[..., Any],
    on_message: Callable[..., Any] | None = None,
    instructions: str = "",
    audience: str = "expert",
) -> dict[str, int | float]:
    """Generate a reveal.js presentation from experiment results.

    Returns a dict with usage totals: tokens_in, tokens_out, cost_usd, agent_calls.
    """
    import tomllib

    from urika.core.presentation import parse_slide_json, render_presentation

    registry = AgentRegistry()
    registry.discover()

    _empty_usage: dict[str, int | float] = {
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "agent_calls": 0,
    }

    pres_role = registry.get("presentation_agent")
    if pres_role is None:
        return _empty_usage

    progress("agent", "Presentation agent — creating slide deck")

    config = pres_role.build_config(
        project_dir=project_dir, experiment_id=experiment_id, audience=audience
    )
    prompt = f"Create a presentation for experiment {experiment_id}."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"
    result = await runner.run(
        config,
        format_audience_context(audience) + prompt,
        on_message=on_message,
    )
    _pres_usage: dict[str, int | float] = {
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": result.cost_usd or 0.0,
        "agent_calls": 1,
    }

    if not result.success:
        return _pres_usage

    slide_data = parse_slide_json(result.text_output)
    if slide_data is None:
        return _pres_usage

    # Read theme preference
    theme = "light"
    toml_path = project_dir / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tdata = tomllib.load(f)
            theme = tdata.get("preferences", {}).get("presentation_theme", "light")
        except Exception as exc:
            logger.warning("Presentation theme loading failed: %s", exc)

    if experiment_id:
        experiment_dir = project_dir / "experiments" / experiment_id
        output_dir = experiment_dir / "presentation"
        render_presentation(
            slide_data,
            output_dir,
            theme=theme,
            experiment_dir=experiment_dir,
        )
    else:
        # Project-level presentation — gather figures from all experiments
        output_dir = project_dir / "projectbook" / "presentation"
        render_presentation(
            slide_data,
            output_dir,
            theme=theme,
            experiment_dir=None,
        )
        # Copy figures from all experiments into presentation/figures/
        import shutil

        pres_figures = output_dir / "figures"
        pres_figures.mkdir(exist_ok=True)
        experiments_dir = project_dir / "experiments"
        if experiments_dir.exists():
            for exp_dir in sorted(experiments_dir.iterdir()):
                artifacts = exp_dir / "artifacts"
                if artifacts.is_dir():
                    for fig in artifacts.iterdir():
                        if fig.is_file() and fig.suffix.lower() in (
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".svg",
                            ".gif",
                        ):
                            shutil.copy2(fig, pres_figures / f"{exp_dir.name}_{fig.name}")

    progress("result", f"Presentation saved to {output_dir}/index.html")
    return _pres_usage


async def _async_generate_summary(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    on_message: Callable[..., Any] | None = None,
) -> tuple[str, dict[str, int | float]]:
    """Call report agent to write a short project status summary.

    Returns (summary_text, usage_dict).
    """
    import json as _json

    _empty_usage: dict[str, int | float] = {
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "agent_calls": 0,
    }

    registry = AgentRegistry()
    registry.discover()

    # Use report_agent (not evaluator) — this is a writing task, not evaluation
    report_role = registry.get("report_agent")
    if report_role is None:
        return "", _empty_usage

    # Build context from methods.json and progress
    methods_path = project_dir / "methods.json"
    methods_info = ""
    if methods_path.exists():
        try:
            mdata = _json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            methods_info = f"{len(mlist)} methods tried.\n"
            for m in mlist[-5:]:  # last 5 methods
                metrics = m.get("metrics", {})
                # Show first numeric metric
                for k, v in metrics.items():
                    if isinstance(v, (int, float)):
                        methods_info += f"  {m['name']}: {k}={v}\n"
                        break
        except Exception as exc:
            logger.warning("Methods info loading failed: %s", exc)

    exp_progress = load_progress(project_dir, experiment_id)
    runs = exp_progress.get("runs", [])
    last_obs = ""
    if runs:
        last_obs = runs[-1].get("observation", "")[:300]

    prompt = (
        "Write a 2-3 sentence summary of the current project status for a README.md. "
        "Be specific about key findings and numbers. No markdown headers, just a paragraph.\n\n"
        f"Latest experiment: {experiment_id}\n"
        f"Runs in this experiment: {len(runs)}\n"
        f"{methods_info}\n"
        f"Latest observation: {last_obs}\n"
    )

    config = report_role.build_config(
        project_dir=project_dir, experiment_id=experiment_id
    )
    config.max_turns = 3  # Keep it short

    # README summary doesn't take an audience param — default to
    # ``standard`` so the audience-context block is non-empty and the
    # system prompt stays byte-stable across calls.
    result = await runner.run(
        config, format_audience_context("standard") + prompt, on_message=on_message
    )
    _result_usage: dict[str, int | float] = {
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_usd": result.cost_usd or 0.0,
        "agent_calls": 1,
    }
    if result.success and result.text_output:
        text = result.text_output.strip()
        # Remove any JSON blocks if agent included them
        import re

        text = re.sub(r"```(?:json|JSON).*?```", "", text, flags=re.DOTALL).strip()
        # Take first paragraph
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            return paragraphs[0], _result_usage
    return "", _result_usage
