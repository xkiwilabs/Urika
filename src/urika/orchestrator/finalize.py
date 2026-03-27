"""Finalize a project — produce polished deliverables."""

from __future__ import annotations

import logging
from pathlib import Path

from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentRunner

logger = logging.getLogger(__name__)


async def finalize_project(
    project_dir: Path,
    runner: AgentRunner,
    on_progress: object = None,
    on_message: object = None,
    *,
    instructions: str = "",
) -> dict:
    """Run the finalization sequence: Finalizer -> Report -> Presentation -> README."""
    progress = on_progress or (lambda e, d="": None)
    registry = AgentRegistry()
    registry.discover()

    # Step 1: Finalizer Agent — select methods, write code, produce findings.json
    progress("agent", "Finalizer — selecting methods and writing code")
    finalizer_role = registry.get("finalizer")
    if finalizer_role is None:
        return {"error": "Finalizer agent not found"}

    config = finalizer_role.build_config(project_dir=project_dir)
    prompt = (
        "Finalize this project. Read all experiments, select the best methods, "
        "write standalone production-ready code, generate findings.json, "
        "requirements.txt, and reproduce scripts."
    )
    if instructions:
        prompt += f"\n\nUser instructions: {instructions}"
    result = await runner.run(
        config,
        prompt,
        on_message=on_message,
    )

    if not result.success:
        return {"error": result.error}

    # Step 2: Report Agent — write final report from findings.json
    progress("agent", "Report agent — writing final report")
    report_role = registry.get("report_agent")
    if report_role is not None:
        report_config = report_role.build_config(
            project_dir=project_dir, experiment_id=""
        )
        report_result = await runner.run(
            report_config,
            "Read projectbook/findings.json and write a comprehensive final report "
            "at projectbook/final-report.md. Include figures from projectbook/figures/. "
            "Structure: Abstract, Introduction, Methods, Results, Discussion, "
            "Reproducibility, References.",
            on_message=on_message,
        )
        if report_result.success:
            progress("result", "Final report written")
        else:
            progress("result", "Final report generation failed")

    # Step 3: Presentation Agent — final presentation from findings.json
    progress("agent", "Presentation agent — creating final presentation")
    pres_role = registry.get("presentation_agent")
    if pres_role is not None:
        pres_config = pres_role.build_config(
            project_dir=project_dir, experiment_id=""
        )
        pres_result = await runner.run(
            pres_config,
            "Read projectbook/findings.json and create a polished final presentation. "
            "Include figures from projectbook/figures/. "
            "This is the definitive project presentation for sharing with colleagues.",
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
                output_dir = project_dir / "projectbook" / "final-presentation"
                render_presentation(slide_data, output_dir, theme=theme)

                # Copy project-level figures into the presentation directory
                project_figures = project_dir / "projectbook" / "figures"
                if project_figures.exists():
                    import shutil

                    pres_figures = output_dir / "figures"
                    pres_figures.mkdir(exist_ok=True)
                    for fig in project_figures.iterdir():
                        if fig.is_file():
                            shutil.copy2(fig, pres_figures / fig.name)

                progress("result", "Final presentation saved")

    # Step 4: Update README
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
