"""Finalize a project — produce polished deliverables."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from urika.agents.audience import format_audience_context
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentRunner
from urika.core.report_writer import extract_report_markdown, write_versioned

logger = logging.getLogger(__name__)


async def finalize_project(
    project_dir: Path,
    runner: AgentRunner,
    on_progress: Callable[..., Any] | None = None,
    on_message: Callable[..., Any] | None = None,
    *,
    instructions: str = "",
    audience: str = "expert",
    draft: bool = False,
) -> dict:
    """Run the finalization sequence: Finalizer -> Report -> Presentation -> README.

    When *draft* is True, outputs go to ``projectbook/draft/`` with interim
    framing (progress summary rather than final deliverables).  Standalone
    method scripts, requirements.txt, reproduce scripts, and README updates
    are skipped.
    """
    progress = on_progress or (lambda e, d="": None)
    registry = AgentRegistry()
    registry.discover()

    # Determine output paths based on draft mode
    if draft:
        findings_rel = "projectbook/draft/findings.json"
        figures_rel = "projectbook/draft/figures/"
        report_rel = "projectbook/draft/report.md"
        pres_rel = "projectbook/draft/presentation"
    else:
        findings_rel = "projectbook/findings.json"
        figures_rel = "projectbook/figures/"
        report_rel = "projectbook/final-report.md"
        pres_rel = "projectbook/final-presentation"

    # Step 1: Finalizer Agent — select methods, write code, produce findings.json
    label = "Draft summary" if draft else "Finalizer"
    progress("agent", f"{label} — selecting methods and writing code")
    finalizer_role = registry.get("finalizer")
    if finalizer_role is None:
        return {"error": "Finalizer agent not found"}

    config = finalizer_role.build_config(project_dir=project_dir, audience=audience)

    if draft:
        prompt = (
            "Create an interim summary of this project's progress. "
            "Read all completed experiments and summarize findings so far. "
            f"Write a draft findings summary to {findings_rel}, "
            f"generate summary figures to {figures_rel}, "
            "but do NOT write final method scripts, requirements.txt, or reproduce scripts. "
            "This is a mid-project checkpoint, not a finalization."
        )
    else:
        prompt = (
            "Finalize this project. Read all experiments, select the best methods, "
            "write standalone production-ready code, generate findings.json, "
            "requirements.txt, and reproduce scripts."
        )
    if instructions:
        prompt += f"\n\nUser instructions: {instructions}"
    result = await runner.run(
        config,
        format_audience_context(audience) + prompt,
        on_message=on_message,
    )

    if not result.success:
        return {"error": result.error}

    # Step 1b: Deterministic artifacts from the findings.json the
    # finalizer just wrote — model cards per final method. Pure code,
    # no agent call. Best-effort: a failure here logs + emits a
    # progress event but never blocks the rest of the finalize
    # sequence. Skipped in draft mode (no final methods exist yet).
    if not draft:
        try:
            from urika.core.model_cards import generate_model_cards

            card_paths = generate_model_cards(project_dir, audience=audience)
            if card_paths:
                progress("result", f"Model cards written ({len(card_paths)})")
        except Exception as exc:
            logger.warning("Model card generation failed: %s", exc)
            progress("result", "Model card generation failed — continuing")
        try:
            from urika.core.metrics_glossary import write_metrics_glossary

            glossary_path = write_metrics_glossary(project_dir)
            if glossary_path is not None:
                progress("result", "Metrics glossary written (projectbook/METRICS.md)")
        except Exception as exc:
            logger.warning("Metrics glossary generation failed: %s", exc)
            progress("result", "Metrics glossary generation failed — continuing")
        try:
            from urika.core.notebook_export import write_reproduce_notebook

            notebook_path = write_reproduce_notebook(project_dir)
            if notebook_path is not None:
                progress(
                    "result",
                    "Reproduce notebook written (projectbook/reproduce.ipynb)",
                )
        except Exception as exc:
            logger.warning("Reproduce notebook generation failed: %s", exc)
            progress("result", "Reproduce notebook generation failed — continuing")

    # Step 2: Report Agent — write report from findings.json
    report_label = "draft progress report" if draft else "final report"
    progress("agent", f"Report agent — writing {report_label}")
    report_role = registry.get("report_agent")
    if report_role is not None:
        report_config = report_role.build_config(
            project_dir=project_dir, experiment_id="", audience=audience
        )
        if draft:
            report_prompt = (
                f"Read {findings_rel} and produce an interim progress report. "
                f"Output ONLY the report as GitHub-flavored markdown — your "
                f"response becomes {report_rel} verbatim. Do NOT attempt to "
                "write any files; you have no file-writing tools, so your reply "
                "IS the report. Begin directly with the report title as a "
                'top-level `# ` heading — no preamble, no "I\'ll write…", no '
                "closing remarks. Reference figures with relative paths like "
                f"`figures/<name>.png` (they live in {figures_rel}). "
                "Structure: Summary of Progress, Methods Explored, "
                "Current Best Results, Open Questions, Next Steps."
            )
        else:
            report_prompt = (
                "Read projectbook/findings.json and produce a comprehensive "
                "final report. Output ONLY the report as GitHub-flavored "
                "markdown — your response becomes projectbook/final-report.md "
                "verbatim. Do NOT attempt to write any files; you have no "
                "file-writing tools, so your reply IS the report. Begin directly "
                "with the report title as a top-level `# ` heading — no preamble, "
                'no "I\'ll write…", no closing remarks. Reference figures with '
                "relative paths like `figures/<name>.png` (they live in "
                "projectbook/figures/). Structure: Abstract, Introduction, "
                "Methods, Results, Discussion, Reproducibility, References."
            )
        report_prompt += (
            " For assumption checks, each experiment's latest evaluator "
            "assessment (including assumptions_detail) is persisted at "
            "experiments/<experiment_id>/labbook/evaluation.json."
        )
        # Inject project memory + the rolling advisor-history summary
        # via the shared ``format_report_context`` helper (mirrors
        # planning and advisor — same heading text, same loader). The
        # final report is the highest-stakes write surface, so user
        # preferences and rejected framings captured to memory must
        # land here too.
        final_report_input = format_audience_context(audience) + report_prompt
        try:
            from urika.agents.roles.report_agent import format_report_context

            _ctx_block = format_report_context(project_dir)
            if _ctx_block:
                final_report_input = f"{_ctx_block}{final_report_input}"
        except Exception as exc:
            logger.warning("Report context block unavailable: %s", exc)
        report_result = await runner.run(
            report_config,
            final_report_input,
            on_message=on_message,
        )
        # The report agent has no Write tool — its reply IS the report.
        # Reject narration ("I'll write…", "Let me read…") so it never
        # clobbers a real report; only a markdown-leading, substantial
        # body is written.
        body = (
            extract_report_markdown(report_result.text_output)
            if report_result.success
            else None
        )
        if body is not None:
            report_path = project_dir / report_rel
            report_path.parent.mkdir(parents=True, exist_ok=True)
            write_versioned(report_path, body + "\n")
            progress("result", f"{report_label.capitalize()} written")
        elif report_result.success:
            progress(
                "result",
                f"{report_label.capitalize()}: agent returned no usable "
                "report — previous report kept",
            )
        else:
            progress("result", f"{report_label.capitalize()} generation failed")

    # Step 3: Presentation Agent — presentation from findings.json
    pres_label = "draft presentation" if draft else "final presentation"
    progress("agent", f"Presentation agent — creating {pres_label}")
    pres_role = registry.get("presentation_agent")
    if pres_role is not None:
        pres_config = pres_role.build_config(
            project_dir=project_dir, experiment_id="", audience=audience
        )
        if draft:
            pres_prompt = (
                f"Read {findings_rel} and create a progress presentation. "
                f"Include figures from {figures_rel}. "
                "This is an interim project summary for review, not the final presentation."
            )
        else:
            pres_prompt = (
                "Read projectbook/findings.json and create a polished final presentation. "
                "Include figures from projectbook/figures/. "
                "This is the definitive project presentation for sharing with colleagues."
            )
        pres_result = await runner.run(
            pres_config,
            format_audience_context(audience) + pres_prompt,
            on_message=on_message,
        )
        if pres_result.success:
            # Render the presentation
            from urika.core.presentation import parse_slide_json, render_presentation

            slide_data = parse_slide_json(pres_result.text_output)
            if slide_data:
                import tomllib

                theme = "light"
                toml_path = project_dir / "urika.toml"
                if toml_path.exists():
                    try:
                        with open(toml_path, "rb") as f:
                            tdata = tomllib.load(f)
                        theme = tdata.get("preferences", {}).get(
                            "presentation_theme", "light"
                        )
                    except Exception as exc:
                        logger.warning("Presentation theme loading failed: %s", exc)
                output_dir = project_dir / pres_rel
                # The renderer resolves project-level figures across all
                # experiments (and projectbook/figures) from project_dir and
                # copies exactly the referenced ones with collision-free names.
                render_presentation(
                    slide_data,
                    output_dir,
                    theme=theme,
                    project_dir=project_dir,
                )

                # Belt-and-braces figure copies. The renderer already searches
                # projectbook/figures, but draft mode keeps its figures in a
                # separate dir that the renderer also resolves; copying here is
                # harmless and keeps draft decks self-contained.
                import shutil

                pres_figures = output_dir / "figures"
                pres_figures.mkdir(exist_ok=True)
                if draft:
                    # In draft mode, also look in draft figures directory
                    draft_figures = project_dir / "projectbook" / "draft" / "figures"
                    if draft_figures.exists():
                        for fig in draft_figures.iterdir():
                            if fig.is_file():
                                shutil.copy2(fig, pres_figures / fig.name)
                project_figures = project_dir / "projectbook" / "figures"
                if project_figures.exists():
                    for fig in project_figures.iterdir():
                        if fig.is_file():
                            shutil.copy2(fig, pres_figures / fig.name)

                progress("result", f"{pres_label.capitalize()} saved")

    # Step 4: Update README (skipped in draft mode)
    if not draft:
        progress("agent", "Updating README")
        try:
            import json

            from urika.core.readme_generator import write_readme

            # Try to get a summary from findings.json
            findings_path = project_dir / "projectbook" / "findings.json"
            summary = ""
            if findings_path.exists():
                try:
                    findings = json.loads(findings_path.read_text(encoding="utf-8"))
                    summary = findings.get("answer", "")
                except Exception as exc:
                    logger.warning("Findings JSON parsing failed: %s", exc)
            write_readme(project_dir, summary=summary)
            progress("result", "README updated with final findings")
        except Exception as exc:
            logger.warning("README update failed: %s", exc)

    return {"success": True}
