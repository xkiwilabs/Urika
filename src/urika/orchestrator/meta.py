"""Meta-orchestrator — manages experiment-to-experiment flow."""

from __future__ import annotations

import click
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
    review_criteria: bool = False,
    on_progress: object = None,
    on_message: object = None,
    get_user_input: object = None,
    pause_controller: object = None,
) -> dict[str, Any]:
    """Run experiments until criteria met or limits reached.

    Modes:
        checkpoint: pause between experiments for user input
        capped: run up to max_experiments with no pauses
        unlimited: run until advisor says done (hard cap 50)
    """
    from urika.cli_display import print_step, print_success
    from urika.core.experiment import create_experiment
    from urika.orchestrator import run_experiment

    safety_cap = 50 if mode == "unlimited" else max_experiments
    results = []

    progress = on_progress or (lambda e, d="": None)

    for exp_num in range(safety_cap):
        # Determine next experiment via advisor
        progress("agent", "Advisor agent — proposing next experiment")
        next_exp = await _determine_next(project_dir, runner, instructions, on_message)
        if next_exp is None:
            print_step("Advisor: no further experiments to suggest.")
            break

        exp_name = next_exp.get("name", f"auto-{exp_num + 1}").replace(" ", "-").lower()
        description = next_exp.get("method", next_exp.get("description", ""))

        # Create experiment
        exp = create_experiment(
            project_dir, name=exp_name, hypothesis=description[:500]
        )
        print_step(f"Experiment {exp_num + 1}: {exp.experiment_id}")

        # Run it
        result = await run_experiment(
            project_dir,
            exp.experiment_id,
            runner,
            max_turns=max_turns,
            review_criteria=review_criteria,
            on_progress=on_progress,
            on_message=on_message,
            instructions=instructions,
            get_user_input=get_user_input,
            pause_controller=pause_controller,
        )
        results.append(result)

        # Check if experiment was paused, stopped, or request pending
        if result.get("status") in ("paused", "stopped"):
            break
        if pause_controller is not None and (
            pause_controller.is_pause_requested()
            or pause_controller.is_stop_requested()
        ):
            break

        # Checkpoint
        if mode == "checkpoint":
            choice = click.prompt(
                "\n  Continue? [next/stop/instructions]",
                type=click.Choice(["next", "stop", "instructions"]),
                default="next",
            )
            if choice == "stop":
                break
            if choice == "instructions":
                instructions = click.prompt("  Instructions").strip()

        # Check if criteria fully met
        if _criteria_fully_met(project_dir):
            print_success("All criteria met.")
            break

    # Finalize after all experiments complete (skip if paused)
    paused = pause_controller is not None and pause_controller.is_pause_requested()
    if results and not paused:
        try:
            from urika.orchestrator.finalize import finalize_project

            progress("phase", "Finalizing project")
            await finalize_project(project_dir, runner, on_progress, on_message)
        except Exception:
            pass  # Finalization is best-effort

    return {
        "experiments_run": len(results),
        "results": results,
        "autonomous_state": {
            "mode": mode,
            "instructions": instructions,
            "max_experiments": max_experiments,
            "experiments_completed": len(results),
        }
        if pause_controller and pause_controller.is_pause_requested()
        else None,
    }


async def _determine_next(
    project_dir: Path,
    runner: AgentRunner,
    instructions: str,
    on_message: object,
) -> dict[str, Any] | None:
    """Call advisor to propose next experiment."""
    from urika.agents.registry import AgentRegistry
    from urika.orchestrator.parsing import parse_suggestions

    registry = AgentRegistry()
    registry.discover()
    advisor = registry.get("advisor_agent")
    if advisor is None:
        return None

    context = "Propose the next experiment.\n"
    if instructions:
        context += f"User instructions: {instructions}\n"

    config = advisor.build_config(project_dir=project_dir, experiment_id="")
    result = await runner.run(config, context, on_message=on_message)

    if not result.success:
        return None

    parsed = parse_suggestions(result.text_output)
    if parsed and parsed.get("suggestions"):
        return parsed["suggestions"][0]
    return None


def _criteria_fully_met(project_dir: Path) -> bool:
    """Check if all criteria are satisfied across all experiments.

    Loads the latest criteria and checks the best metrics from every
    experiment's progress.json against those criteria.  Returns True
    only when **all** threshold criteria pass for at least one run.
    """
    from urika.core.criteria import load_criteria
    from urika.evaluation.criteria import validate_criteria

    c = load_criteria(project_dir)
    if c is None:
        return False
    criteria = c.criteria
    # Only check entries that have min/max thresholds
    threshold = criteria.get("threshold", {})
    if not threshold:
        return False  # No threshold = exploratory, never auto-done

    # Collect best metrics across all experiments
    experiments_dir = project_dir / "experiments"
    if not experiments_dir.is_dir():
        return False

    for exp_dir in sorted(experiments_dir.iterdir()):
        progress_file = exp_dir / "progress.json"
        if not progress_file.exists():
            continue
        try:
            import json

            data = json.loads(progress_file.read_text(encoding="utf-8"))
            for run in data.get("runs", []):
                metrics = run.get("metrics", {})
                if not metrics:
                    continue
                passed, _failures = validate_criteria(metrics, threshold)
                if passed:
                    return True
        except Exception:
            continue
    return False
