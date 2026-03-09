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
    parse_run_records,
    parse_suggestions,
)


async def run_experiment(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    *,
    max_turns: int = 50,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the orchestration loop for an experiment.

    Cycles through task_agent -> evaluator -> suggestion_agent until
    criteria are met or max_turns is reached.

    If *resume* is True, resumes a previously paused session instead of
    starting a new one.
    """
    registry = AgentRegistry()
    registry.discover()

    if resume:
        try:
            state = resume_session(project_dir, experiment_id)
        except (FileNotFoundError, RuntimeError) as exc:
            return {"status": "failed", "error": str(exc), "turns": 0}
        start_turn = state.current_turn + 1

        # Use the last run's next_step as the initial task prompt, if available
        task_prompt = "Continue the experiment with a different approach."
        try:
            progress = load_progress(project_dir, experiment_id)
            runs = progress.get("runs", [])
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

    # --- Pre-loop: knowledge scan ---
    knowledge_summary = build_knowledge_summary(project_dir)
    if knowledge_summary:
        lit_role = registry.get("literature_agent")
        if lit_role is not None:
            lit_config = lit_role.build_config(project_dir=project_dir)
            await runner.run(
                lit_config,
                "Scan the knowledge directory and summarize available knowledge.",
            )
        task_prompt = knowledge_summary + "\n\n" + task_prompt

    for turn in range(start_turn, max_turns + 1):
        try:
            # --- task_agent ---
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
            task_result = await runner.run(task_config, task_prompt)

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

            # --- evaluator ---
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
            eval_result = await runner.run(eval_config, task_result.text_output)

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
                complete_session(project_dir, experiment_id)
                return {"status": "completed", "turns": turn}

            # --- suggestion_agent ---
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
            suggest_result = await runner.run(suggest_config, eval_result.text_output)

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

            # --- optional tool_builder ---
            if suggestions and suggestions.get("needs_tool"):
                tool_role = registry.get("tool_builder")
                if tool_role is not None:
                    tool_config = tool_role.build_config(project_dir=project_dir)
                    await runner.run(tool_config, json.dumps(suggestions))

            # Build next task prompt from suggestions
            if suggestions:
                task_prompt = json.dumps(suggestions)
            else:
                task_prompt = "Continue the experiment with a different approach."

            # --- optional literature_agent ---
            if suggestions and suggestions.get("needs_literature"):
                lit_role = registry.get("literature_agent")
                if lit_role is not None:
                    lit_config = lit_role.build_config(project_dir=project_dir)
                    lit_result = await runner.run(lit_config, json.dumps(suggestions))
                    if lit_result.success and lit_result.text_output:
                        task_prompt = lit_result.text_output + "\n\n" + task_prompt

            update_turn(project_dir, experiment_id)

        except Exception as exc:
            fail_session(project_dir, experiment_id, error=str(exc))
            return {"status": "failed", "error": str(exc), "turns": turn}

    # Reached max_turns without criteria being met
    complete_session(project_dir, experiment_id)
    return {"status": "completed", "turns": max_turns}
