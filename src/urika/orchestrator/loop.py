"""Orchestrator loop: cycle agents through experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentRunner
from urika.core.progress import append_run, load_progress
from urika.core.session import (
    complete_session,
    fail_session,
    resume_session,
    start_session,
    update_turn,
)
from urika.orchestrator.knowledge import build_knowledge_summary
from urika.orchestrator.parsing import (
    parse_evaluation,
    parse_method_plan,
    parse_run_records,
    parse_suggestions,
)


def _noop_callback(event: str, detail: str = "") -> None:
    """Default no-op progress callback."""


async def _generate_reports(
    project_dir: Path,
    experiment_id: str,
    progress: object,
    runner: AgentRunner | None = None,
    on_message: object = None,
) -> None:
    """Generate labbook reports and update README after experiment completion."""
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
    except Exception:
        pass  # Reports are best-effort, don't fail the experiment

    # Update project README.md with agent-written summary
    try:
        from urika.core.readme_generator import write_readme

        summary = ""
        if runner is not None:
            try:
                summary = await _async_generate_summary(
                    project_dir, experiment_id, runner, on_message
                )
            except Exception:
                pass
        write_readme(project_dir, summary=summary)
        progress("result", "README.md updated")
    except Exception:
        pass


async def _async_generate_summary(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    on_message: object = None,
) -> str:
    """Call evaluator agent to write a short project status summary."""
    import json as _json

    registry = AgentRegistry()
    registry.discover()

    eval_role = registry.get("evaluator")
    if eval_role is None:
        return ""

    # Build context from methods.json and progress
    methods_path = project_dir / "methods.json"
    methods_info = ""
    if methods_path.exists():
        try:
            mdata = _json.loads(methods_path.read_text())
            mlist = mdata.get("methods", [])
            methods_info = f"{len(mlist)} methods tried.\n"
            for m in mlist[-5:]:  # last 5 methods
                metrics = m.get("metrics", {})
                acc = metrics.get(
                    "top1_accuracy",
                    metrics.get("accuracy", ""),
                )
                if acc:
                    methods_info += f"  {m['name']}: {acc}\n"
        except Exception:
            pass

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

    config = eval_role.build_config(
        project_dir=project_dir, experiment_id=experiment_id
    )
    config.max_turns = 3  # Keep it short

    result = await runner.run(config, prompt, on_message=on_message)
    if result.success and result.text_output:
        # Strip any JSON blocks, just get the text
        text = result.text_output.strip()
        # Remove JSON blocks if agent included them
        import re

        text = re.sub(r"```json.*?```", "", text, flags=re.DOTALL).strip()
        # Take first paragraph
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if paragraphs:
            return paragraphs[0]
    return ""


def _print_run_summary(project_dir: Path, experiment_id: str, progress: object) -> None:
    """Print a summary of what was achieved in this experiment."""
    try:
        exp_progress = load_progress(project_dir, experiment_id)
        runs = exp_progress.get("runs", [])
        if not runs:
            return

        progress("phase", "")
        progress("phase", "━━━ Run Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Methods tried
        methods = [r["method"] for r in runs]
        progress("result", f"{len(runs)} runs across {len(set(methods))} methods")

        # Best metrics
        best_acc = None
        best_method = None
        for r in runs:
            for key in ("top1_accuracy", "accuracy", "loso_top1_accuracy"):
                val = r.get("metrics", {}).get(key)
                if val is not None and (best_acc is None or val > best_acc):
                    best_acc = val
                    best_method = r["method"]

        if best_acc is not None:
            progress("result", f"Best: {best_method} ({best_acc:.1%} accuracy)")

        # Key observations from last run
        last = runs[-1]
        if last.get("observation"):
            obs = last["observation"][:200]
            if len(last["observation"]) > 200:
                obs += "…"
            progress("phase", f"Latest: {obs}")

        # Next step from last run
        if last.get("next_step"):
            ns = last["next_step"][:150]
            if len(last["next_step"]) > 150:
                ns += "…"
            progress("phase", f"Next: {ns}")

        progress("phase", "")
    except Exception:
        pass


async def run_experiment(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    *,
    max_turns: int = 50,
    resume: bool = False,
    on_progress: object = None,
    on_message: object = None,
    instructions: str = "",
) -> dict[str, Any]:
    """Run the orchestration loop for an experiment.

    Cycles through planning -> task -> evaluator -> suggestion until
    criteria are met or max_turns is reached.

    If *resume* is True, resumes a previously paused session instead of
    starting a new one.

    *on_progress* is an optional callback ``(event, detail) -> None``
    called at key points in the loop.

    *on_message* is an optional callback forwarded to ``runner.run()``
    that receives each SDK message as it streams in.

    *instructions* is optional user guidance prepended to the initial prompt.
    """
    progress = on_progress or _noop_callback
    registry = AgentRegistry()
    registry.discover()

    if resume:
        try:
            state = resume_session(project_dir, experiment_id)
            start_turn = state.current_turn + 1
            if state.max_turns is not None:
                max_turns = state.max_turns
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "turns": 0}

        # Use the last run's next_step as the initial task prompt, if available
        task_prompt = "Continue the experiment with a different approach."
        try:
            prev_progress = load_progress(project_dir, experiment_id)
            runs = prev_progress.get("runs", [])
            if runs:
                last_next_step = runs[-1].get("next_step", "")
                if last_next_step:
                    task_prompt = last_next_step
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    else:
        try:
            start_session(project_dir, experiment_id, max_turns=max_turns)
        except Exception as exc:
            return {"status": "failed", "error": str(exc), "turns": 0}
        start_turn = 1
        task_prompt = "Begin the experiment. Try an initial approach."

    # Prepend user instructions if provided
    if instructions:
        task_prompt = f"User instructions: {instructions}\n\n{task_prompt}"

    # --- Pre-loop: knowledge scan ---
    progress("phase", "Scanning knowledge base")
    try:
        knowledge_summary = build_knowledge_summary(project_dir)
        if knowledge_summary:
            lit_role = registry.get("literature_agent")
            if lit_role is not None:
                lit_config = lit_role.build_config(project_dir=project_dir)
                await runner.run(
                    lit_config,
                    "Scan the knowledge directory and summarize available knowledge.",
                    on_message=on_message,
                )
            task_prompt = knowledge_summary + "\n\n" + task_prompt
    except Exception as exc:
        fail_session(project_dir, experiment_id, error=str(exc))
        return {"status": "failed", "error": str(exc), "turns": 0}

    for turn in range(start_turn, max_turns + 1):
        progress("turn", f"Turn {turn}/{max_turns}")
        try:
            # --- planning_agent (optional) ---
            plan_role = registry.get("planning_agent")
            if plan_role is not None:
                progress("agent", "Planning agent — designing method")
                plan_config = plan_role.build_config(
                    project_dir=project_dir, experiment_id=experiment_id
                )
                plan_result = await runner.run(
                    plan_config, task_prompt, on_message=on_message
                )

                if not plan_result.success:
                    fail_session(
                        project_dir,
                        experiment_id,
                        error=plan_result.error or "planning_agent failed",
                    )
                    return {
                        "status": "failed",
                        "error": plan_result.error or "planning_agent failed",
                        "turns": turn,
                    }

                method_plan = parse_method_plan(plan_result.text_output)

                # Handle planning agent's tool/literature requests
                if method_plan and method_plan.get("needs_tool"):
                    progress("agent", "Tool builder — creating required tool")
                    tool_role = registry.get("tool_builder")
                    if tool_role is not None:
                        tool_config = tool_role.build_config(project_dir=project_dir)
                        await runner.run(
                            tool_config,
                            json.dumps(method_plan),
                            on_message=on_message,
                        )

                if method_plan and method_plan.get("needs_literature"):
                    progress("agent", "Literature agent — searching knowledge")
                    lit_role = registry.get("literature_agent")
                    if lit_role is not None:
                        lit_config = lit_role.build_config(project_dir=project_dir)
                        lit_result = await runner.run(
                            lit_config,
                            method_plan.get(
                                "literature_query", json.dumps(method_plan)
                            ),
                            on_message=on_message,
                        )
                        if lit_result.success and lit_result.text_output:
                            task_input = (
                                lit_result.text_output
                                + "\n\n"
                                + plan_result.text_output
                            )
                        else:
                            task_input = plan_result.text_output
                    else:
                        task_input = plan_result.text_output
                else:
                    task_input = plan_result.text_output
            else:
                task_input = task_prompt

            # --- task_agent ---
            progress("agent", "Task agent — running experiment")
            task_role = registry.get("task_agent")
            if task_role is None:
                fail_session(
                    project_dir, experiment_id, error="task_agent role not found"
                )
                return {
                    "status": "failed",
                    "error": "task_agent role not found",
                    "turns": turn,
                }

            task_config = task_role.build_config(
                project_dir=project_dir, experiment_id=experiment_id
            )
            task_result = await runner.run(
                task_config, task_input, on_message=on_message
            )

            if not task_result.success:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=task_result.error or "task_agent failed",
                )
                return {
                    "status": "failed",
                    "error": task_result.error or "task_agent failed",
                    "turns": turn,
                }

            # Parse and record runs
            runs = parse_run_records(task_result.text_output)
            for run in runs:
                append_run(project_dir, experiment_id, run)
            if runs:
                progress("result", f"Recorded {len(runs)} run(s)")

            # Register methods in project registry
            from urika.core.method_registry import register_method

            for run in runs:
                register_method(
                    project_dir,
                    name=run.method,
                    description=run.observation or run.method,
                    script=f"experiments/{experiment_id}/methods/{run.method}.py",
                    experiment=experiment_id,
                    turn=turn,
                    metrics=run.metrics,
                )
                progress("result", f"Registered method: {run.method}")

            # --- evaluator ---
            progress("agent", "Evaluator — scoring results")
            eval_role = registry.get("evaluator")
            if eval_role is None:
                fail_session(
                    project_dir, experiment_id, error="evaluator role not found"
                )
                return {
                    "status": "failed",
                    "error": "evaluator role not found",
                    "turns": turn,
                }

            eval_config = eval_role.build_config(
                project_dir=project_dir, experiment_id=experiment_id
            )
            eval_result = await runner.run(
                eval_config, task_result.text_output, on_message=on_message
            )

            if not eval_result.success:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=eval_result.error or "evaluator failed",
                )
                return {
                    "status": "failed",
                    "error": eval_result.error or "evaluator failed",
                    "turns": turn,
                }

            evaluation = parse_evaluation(eval_result.text_output)
            if evaluation and evaluation.get("criteria_met"):
                progress("result", "Criteria met!")
                complete_session(project_dir, experiment_id)
                await _generate_reports(
                    project_dir,
                    experiment_id,
                    progress,
                    runner=runner,
                    on_message=on_message,
                )
                _print_run_summary(project_dir, experiment_id, progress)
                return {"status": "completed", "turns": turn}

            # --- suggestion_agent ---
            progress("agent", "Suggestion agent — proposing next steps")
            suggest_role = registry.get("suggestion_agent")
            if suggest_role is None:
                fail_session(
                    project_dir,
                    experiment_id,
                    error="suggestion_agent role not found",
                )
                return {
                    "status": "failed",
                    "error": "suggestion_agent role not found",
                    "turns": turn,
                }

            suggest_config = suggest_role.build_config(
                project_dir=project_dir, experiment_id=experiment_id
            )
            suggest_result = await runner.run(
                suggest_config, eval_result.text_output, on_message=on_message
            )

            if not suggest_result.success:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=suggest_result.error or "suggestion_agent failed",
                )
                return {
                    "status": "failed",
                    "error": suggest_result.error or "suggestion_agent failed",
                    "turns": turn,
                }

            suggestions = parse_suggestions(suggest_result.text_output)

            # Update criteria if suggestion agent proposed changes
            if suggestions and suggestions.get("criteria_update"):
                from urika.core.criteria import append_criteria

                update = suggestions["criteria_update"]
                append_criteria(
                    project_dir,
                    update.get("criteria", {}),
                    set_by="suggestion_agent",
                    turn=turn,
                    rationale=update.get("rationale", ""),
                )
                progress("result", "Criteria updated")

            # Save suggestion for this turn
            suggestions_dir = (
                project_dir / "experiments" / experiment_id / "suggestions"
            )
            suggestions_dir.mkdir(exist_ok=True)
            suggestion_data = {
                "turn": turn,
                "raw_text": suggest_result.text_output,
                "parsed": suggestions,
            }
            (suggestions_dir / f"turn-{turn}.json").write_text(
                json.dumps(suggestion_data, indent=2) + "\n"
            )

            # Build next task prompt from suggestions
            if suggestions:
                task_prompt = json.dumps(suggestions)
            else:
                task_prompt = "Continue the experiment with a different approach."

            update_turn(project_dir, experiment_id)

        except Exception as exc:
            fail_session(project_dir, experiment_id, error=str(exc))
            return {"status": "failed", "error": str(exc), "turns": turn}

    # Reached max_turns without criteria being met
    complete_session(project_dir, experiment_id)
    await _generate_reports(
        project_dir, experiment_id, progress, runner=runner, on_message=on_message
    )
    _print_run_summary(project_dir, experiment_id, progress)
    return {"status": "completed", "turns": max_turns}
