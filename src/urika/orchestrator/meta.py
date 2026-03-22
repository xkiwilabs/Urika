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
    on_progress: object = None,
    on_message: object = None,
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

    for exp_num in range(safety_cap):
        # Determine next experiment via advisor
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
            on_progress=on_progress,
            on_message=on_message,
            instructions=instructions,
        )
        results.append(result)

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

    return {"experiments_run": len(results), "results": results}


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
