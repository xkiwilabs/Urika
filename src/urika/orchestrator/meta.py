"""Meta-orchestrator — manages experiment-to-experiment flow."""

from __future__ import annotations

import logging

import click
from pathlib import Path
from typing import Any, Callable

from urika.agents.runner import AgentRunner

logger = logging.getLogger(__name__)


async def run_project(
    project_dir: Path,
    runner: AgentRunner,
    *,
    mode: str = "checkpoint",
    max_experiments: int = 10,
    max_turns: int = 5,
    instructions: str = "",
    review_criteria: bool = False,
    on_progress: Callable[..., Any] | None = None,
    on_message: Callable[..., Any] | None = None,
    get_user_input: Callable[..., Any] | None = None,
    pause_controller: object = None,
    audience: str = "expert",
) -> dict[str, Any]:
    """Run experiments until criteria met or limits reached.

    Modes:
        checkpoint: pause between experiments for user input
        capped: run up to max_experiments with no pauses
        unlimited: run until advisor says done (hard cap 50)
    """
    from urika.cli_display import print_step
    from urika.core.experiment import create_experiment, list_experiments
    from urika.orchestrator import run_experiment

    safety_cap = 50 if mode == "unlimited" else max_experiments
    results = []

    progress = on_progress or (lambda e, d="": None)

    for exp_num in range(safety_cap):
        # Check for existing pending experiments first (e.g., created but not yet run)
        from urika.core.progress import load_progress

        pending_experiments = [
            e for e in list_experiments(project_dir)
            if load_progress(project_dir, e.experiment_id).get("status")
            in ("pending",)
        ]

        if pending_experiments:
            # Run the most recent pending experiment before asking advisor
            exp = pending_experiments[-1]
            print_step(
                f"Experiment {exp_num + 1}: {exp.experiment_id} (pending)"
            )
        else:
            # Check for pending suggestions from advisor conversations
            next_exp = None
            pending_path = project_dir / "suggestions" / "pending.json"
            if pending_path.exists():
                try:
                    import json as _pjson

                    pdata = _pjson.loads(
                        pending_path.read_text(encoding="utf-8")
                    )
                    psuggest = pdata.get("suggestions", [])
                    if psuggest:
                        next_exp = psuggest[0]
                        # Remove used suggestion, delete file if empty
                        psuggest.pop(0)
                        if psuggest:
                            pending_path.write_text(
                                _pjson.dumps(pdata, indent=2),
                                encoding="utf-8",
                            )
                        else:
                            pending_path.unlink(missing_ok=True)
                        print_step(
                            "Using suggestion from recent advisor conversation"
                        )
                except Exception:
                    pass

            if next_exp is None:
                # No pending suggestions — ask advisor
                progress("agent", "Advisor agent — proposing next experiment")
                next_exp, advisor_text = await _determine_next(
                    project_dir, runner, instructions, on_message
                )

            if next_exp is None:
                print_step("Advisor: no further experiments to suggest.")
                if advisor_text:
                    preview = advisor_text[:500].strip()
                    if len(advisor_text) > 500:
                        preview += "..."
                    click.echo(f"\n  {preview}\n")
                break

            exp_name = next_exp.get("name", f"auto-{exp_num + 1}").replace(" ", "-").lower()
            description = next_exp.get("method", next_exp.get("description", ""))

            # Create experiment
            exp = create_experiment(
                project_dir, name=exp_name, hypothesis=description[:500]
            )
            print_step(f"Experiment {exp_num + 1}: {exp.experiment_id}")

        # Notify: new experiment starting
        description = getattr(exp, "name", "")
        progress(
            "phase",
            f"Starting experiment {exp_num + 1}: {exp.experiment_id}"
            + (f" — {description[:100]}" if description else ""),
        )

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
            audience=audience,
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

    # Finalize after all experiments complete (skip if paused)
    paused = pause_controller is not None and pause_controller.is_pause_requested()
    if results and not paused:
        try:
            from urika.orchestrator.finalize import finalize_project

            progress("phase", "Finalizing project")
            await finalize_project(
                project_dir, runner, on_progress, on_message,
                audience=audience,
            )
        except Exception as exc:
            logger.warning("Finalization failed: %s", exc)

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
    on_message: Callable[..., Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    """Call advisor to propose next experiment."""
    from urika.agents.registry import AgentRegistry
    from urika.orchestrator.parsing import parse_suggestions

    registry = AgentRegistry()
    registry.discover()
    advisor = registry.get("advisor_agent")
    if advisor is None:
        return None, ""

    import json as _json
    import tomllib

    context_parts = []

    # Inject rolling context summary from previous advisor sessions
    from urika.core.advisor_memory import load_context_summary

    context_summary = load_context_summary(project_dir)
    if context_summary:
        context_parts.append(
            f"## Research Context (from previous sessions)\n\n{context_summary}"
        )

    # Project info
    toml_path = project_dir / "urika.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                tconf = tomllib.load(f)
            proj = tconf.get("project", {})
            context_parts.append(f"Project: {proj.get('name', project_dir.name)}")
            context_parts.append(f"Mode: {proj.get('mode', 'exploratory')}")
            q = proj.get("question", "")
            if q:
                context_parts.append(f"Question: {q[:200]}")
        except Exception:
            pass

    # What's been tried
    methods_path = project_dir / "methods.json"
    if methods_path.exists():
        try:
            mdata = _json.loads(methods_path.read_text(encoding="utf-8"))
            methods = mdata.get("methods", [])
            context_parts.append(
                f"\n{len(methods)} methods tried across all experiments."
            )
            for m in methods[-20:]:
                metrics = m.get("metrics", {})
                metric_str = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:3])
                context_parts.append(
                    f"  {m['name']} [{m.get('status', '?')}] {metric_str}"
                )
        except Exception:
            pass

    # Current criteria
    try:
        from urika.core.criteria import load_criteria

        c = load_criteria(project_dir)
        if c:
            context_parts.append(
                f"\nCriteria (v{c.version}): {_json.dumps(c.criteria)[:500]}"
            )
    except Exception:
        pass

    # Experiments run
    try:
        from urika.core.experiment import list_experiments

        experiments = list_experiments(project_dir)
        context_parts.append(f"\nExperiments completed: {len(experiments)}")
        for exp in experiments[-10:]:
            context_parts.append(f"  {exp.experiment_id}: {exp.name}")
    except Exception:
        pass

    if instructions:
        context_parts.append(
            f"\nIMPORTANT — User instructions (follow these): {instructions}"
        )

    context_parts.append(
        "\nBased on the above, propose the next experiment. "
        "If the user gave instructions, follow them. "
        "Only respond with no suggestions if the user's instructions "
        "have been fully addressed AND all promising avenues explored."
    )

    context = "\n".join(context_parts)

    config = advisor.build_config(project_dir=project_dir, experiment_id="")
    result = await runner.run(config, context, on_message=on_message)

    if not result.success:
        return None, result.error or ""

    parsed = parse_suggestions(result.text_output)

    # Save advisor exchange to persistent history (best-effort, no summary update)
    try:
        from urika.core.advisor_memory import append_exchange

        append_exchange(
            project_dir,
            role="advisor",
            text=result.text_output or "",
            source="meta",
            suggestions=(
                parsed["suggestions"]
                if parsed and parsed.get("suggestions")
                else None
            ),
        )
    except Exception:
        pass

    if parsed and parsed.get("suggestions"):
        return parsed["suggestions"][0], result.text_output or ""
    return None, result.text_output or ""


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
