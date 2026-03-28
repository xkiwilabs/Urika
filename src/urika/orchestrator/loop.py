"""Orchestrator loop: cycle agents through experiments."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from urika.agents.config import load_runtime_config
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentRunner
from urika.core.progress import append_run, load_progress
from urika.core.session import (
    complete_session,
    fail_session,
    pause_session,
    resume_session,
    start_session,
    update_turn,
)
from urika.evaluation.leaderboard import update_leaderboard
from urika.orchestrator.context import summarize_task_output
from urika.orchestrator.knowledge import build_knowledge_summary
from urika.orchestrator.parsing import (
    parse_evaluation,
    parse_method_plan,
    parse_run_records,
    parse_suggestions,
)

logger = logging.getLogger(__name__)


# Metrics where lower values are better (errors, losses, p-values)
_LOWER_IS_BETTER = {"rmse", "mae", "mse", "loss", "error", "p_value", "aic", "bic"}


def _detect_primary_metric(
    metrics: dict[str, float],
) -> tuple[str, str]:
    """Detect the primary metric and its direction from a metrics dict.

    Returns (metric_name, direction) where direction is
    'higher_is_better' or 'lower_is_better'. Prefers common metrics
    in this order: r2, accuracy, f1, rmse, mae, then the first numeric key.
    """
    preferred = ["r2", "accuracy", "f1", "rmse", "mae", "mse", "loss"]
    for name in preferred:
        if name in metrics and isinstance(metrics[name], (int, float)):
            direction = (
                "lower_is_better" if name in _LOWER_IS_BETTER else "higher_is_better"
            )
            return name, direction
    # Fallback: first numeric metric
    for name, val in metrics.items():
        if isinstance(val, (int, float)):
            direction = (
                "lower_is_better" if name in _LOWER_IS_BETTER else "higher_is_better"
            )
            return name, direction
    return "", "higher_is_better"


def _noop_callback(event: str, detail: str = "") -> None:
    """Default no-op progress callback."""


async def _generate_reports(
    project_dir: Path,
    experiment_id: str,
    progress: object,
    runner: AgentRunner | None = None,
    on_message: object = None,
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
                progress("agent", "Report agent \u2014 writing experiment narrative")
                config = report_role.build_config(
                    project_dir=project_dir, experiment_id=experiment_id
                )
                result = await runner.run(
                    config,
                    f"Write a detailed narrative report for experiment {experiment_id}.",
                    on_message=on_message,
                )
                _track(result)
                if result.success and result.text_output:
                    from urika.core.report_writer import write_versioned

                    narrative_path = (
                        project_dir
                        / "experiments"
                        / experiment_id
                        / "labbook"
                        / "narrative.md"
                    )
                    narrative_path.parent.mkdir(parents=True, exist_ok=True)
                    write_versioned(narrative_path, result.text_output.strip() + "\n")
                    progress("result", "Experiment narrative written")
        except Exception as exc:
            logger.warning("Experiment narrative generation failed: %s", exc)

    # Generate project-level narrative
    if runner is not None:
        try:
            registry = AgentRegistry()
            registry.discover()
            report_role = registry.get("report_agent")
            if report_role is not None:
                progress("agent", "Report agent \u2014 writing project narrative")
                config = report_role.build_config(
                    project_dir=project_dir, experiment_id=""
                )
                result = await runner.run(
                    config,
                    "Write a project-level narrative report covering all experiments and the research progression.",
                    on_message=on_message,
                )
                _track(result)
                if result.success and result.text_output:
                    from urika.core.report_writer import write_versioned

                    narrative_path = project_dir / "projectbook" / "narrative.md"
                    narrative_path.parent.mkdir(parents=True, exist_ok=True)
                    write_versioned(narrative_path, result.text_output.strip() + "\n")
                    progress("result", "Project narrative written")
        except Exception as exc:
            logger.warning("Project narrative generation failed: %s", exc)

    # Generate presentation slide deck
    if runner is not None:
        try:
            pres_usage = await _generate_presentation(
                project_dir, experiment_id, runner, progress, on_message
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
    progress: object,
    on_message: object = None,
    instructions: str = "",
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
        project_dir=project_dir, experiment_id=experiment_id
    )
    prompt = f"Create a presentation for experiment {experiment_id}."
    if instructions:
        prompt = f"User instructions: {instructions}\n\n{prompt}"
    result = await runner.run(
        config,
        prompt,
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
                            shutil.copy2(fig, pres_figures / fig.name)

    progress("result", f"Presentation saved to {output_dir}/index.html")
    return _pres_usage


async def _async_generate_summary(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    on_message: object = None,
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

    result = await runner.run(config, prompt, on_message=on_message)
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

        # Best metrics — find the first numeric metric, respecting direction
        best_val = None
        best_method = None
        best_metric_name = None
        lower_is_better = False
        for r in runs:
            for key, val in r.get("metrics", {}).items():
                if isinstance(val, (int, float)):
                    if best_metric_name is None:
                        best_metric_name = key
                        lower_is_better = key in _LOWER_IS_BETTER
                    if key == best_metric_name:
                        if best_val is None:
                            best_val = val
                            best_method = r["method"]
                        elif lower_is_better and val < best_val:
                            best_val = val
                            best_method = r["method"]
                        elif not lower_is_better and val > best_val:
                            best_val = val
                            best_method = r["method"]

        if best_val is not None:
            label = best_metric_name.replace("_", " ")
            if 0 <= best_val <= 1:
                progress("result", f"Best: {best_method} ({best_val:.1%} {label})")
            else:
                progress("result", f"Best: {best_method} ({best_val:.4g} {label})")

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
    except Exception as exc:
        logger.warning("Run summary generation failed: %s", exc)


async def run_experiment(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    *,
    max_turns: int = 50,
    review_criteria: bool = False,
    resume: bool = False,
    on_progress: object = None,
    on_message: object = None,
    instructions: str = "",
    get_user_input: object = None,
    pause_controller: object = None,
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

    *get_user_input* is an optional callable ``() -> str`` that returns
    queued user text (or ``""``).  When non-empty the text is prepended to
    the advisor prompt so users can steer experiments mid-run.

    *pause_controller* is an optional ``PauseController`` instance.  When
    provided, the loop checks ``is_pause_requested()`` before each turn and
    gracefully pauses the session if the flag is set.
    """
    progress = on_progress or _noop_callback
    registry = AgentRegistry()
    registry.discover()

    # Usage accumulators — aggregate across all agent calls
    _total_tokens_in = 0
    _total_tokens_out = 0
    _total_cost_usd = 0.0
    _total_agent_calls = 0

    def _usage_dict(status: str, turns: int, **extra: Any) -> dict[str, Any]:
        return {
            "status": status,
            "turns": turns,
            "tokens_in": _total_tokens_in,
            "tokens_out": _total_tokens_out,
            "cost_usd": _total_cost_usd,
            "agent_calls": _total_agent_calls,
            **extra,
        }

    if resume:
        try:
            state = resume_session(project_dir, experiment_id)
            start_turn = state.current_turn + 1
            if state.max_turns is not None:
                max_turns = state.max_turns
        except Exception as exc:
            return _usage_dict("failed", 0, error=str(exc))

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
            return _usage_dict("failed", 0, error=str(exc))
        start_turn = 1
        task_prompt = "Begin the experiment. Try an initial approach."

    # Prepend user instructions if provided
    if instructions:
        task_prompt = f"User instructions: {instructions}\n\n{task_prompt}"

    # Cache runtime config for the entire experiment (doesn't change mid-run)
    runtime_config = load_runtime_config(project_dir)

    # --- Pre-loop: knowledge scan ---
    progress("phase", "Scanning knowledge base")
    knowledge_summary = ""
    try:
        knowledge_summary = build_knowledge_summary(project_dir) or ""
        if knowledge_summary:
            lit_role = registry.get("literature_agent")
            if lit_role is not None:
                progress("agent", "Literature agent \u2014 scanning knowledge base")
                lit_config = lit_role.build_config(project_dir=project_dir)
                lit_result = await runner.run(
                    lit_config,
                    "Scan the knowledge directory and summarize available knowledge.",
                    on_message=on_message,
                )
                _total_tokens_in += lit_result.tokens_in
                _total_tokens_out += lit_result.tokens_out
                _total_cost_usd += lit_result.cost_usd or 0.0
                _total_agent_calls += 1
                # Use the literature agent's output if available
                if lit_result.success and lit_result.text_output:
                    knowledge_summary = lit_result.text_output
            task_prompt = knowledge_summary + "\n\n" + task_prompt
    except Exception as exc:
        logger.warning("Knowledge scan failed: %s", exc)

    for turn in range(start_turn, max_turns + 1):
        # Check for pause request before starting this turn
        if pause_controller is not None and pause_controller.is_pause_requested():
            pause_session(project_dir, experiment_id)
            progress("phase", f"Paused after turn {turn - 1}")
            return _usage_dict("paused", turn - 1)

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
                _total_tokens_in += plan_result.tokens_in
                _total_tokens_out += plan_result.tokens_out
                _total_cost_usd += plan_result.cost_usd or 0.0
                _total_agent_calls += 1

                if not plan_result.success:
                    fail_session(
                        project_dir,
                        experiment_id,
                        error=plan_result.error or "planning_agent failed",
                    )
                    return _usage_dict(
                        "failed",
                        turn,
                        error=plan_result.error or "planning_agent failed",
                    )

                method_plan = parse_method_plan(plan_result.text_output)

                # Handle planning agent's tool/literature requests
                if method_plan and method_plan.get("needs_tool"):
                    progress("agent", "Tool builder — creating required tool")
                    tool_role = registry.get("tool_builder")
                    if tool_role is not None:
                        tool_config = tool_role.build_config(project_dir=project_dir)
                        _tool_result = await runner.run(
                            tool_config,
                            json.dumps(method_plan),
                            on_message=on_message,
                        )
                        _total_tokens_in += _tool_result.tokens_in
                        _total_tokens_out += _tool_result.tokens_out
                        _total_cost_usd += _tool_result.cost_usd or 0.0
                        _total_agent_calls += 1

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
                        _total_tokens_in += lit_result.tokens_in
                        _total_tokens_out += lit_result.tokens_out
                        _total_cost_usd += lit_result.cost_usd or 0.0
                        _total_agent_calls += 1
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

            # --- data_agent (hybrid mode only) ---
            if runtime_config.privacy_mode == "hybrid":
                data_role = registry.get("data_agent")
                if data_role is not None:
                    progress("agent", "Data agent \u2014 extracting features")
                    data_config = data_role.build_config(
                        project_dir=project_dir, experiment_id=experiment_id
                    )
                    data_result = await runner.run(
                        data_config, task_input, on_message=on_message
                    )
                    _total_tokens_in += data_result.tokens_in
                    _total_tokens_out += data_result.tokens_out
                    _total_cost_usd += data_result.cost_usd or 0.0
                    _total_agent_calls += 1
                    if data_result.success and data_result.text_output:
                        task_input = data_result.text_output + "\n\n" + task_input

            # --- task_agent ---
            progress("agent", "Task agent — running experiment")
            task_role = registry.get("task_agent")
            if task_role is None:
                fail_session(
                    project_dir, experiment_id, error="task_agent role not found"
                )
                return _usage_dict(
                    "failed",
                    turn,
                    error="task_agent role not found",
                )

            task_config = task_role.build_config(
                project_dir=project_dir, experiment_id=experiment_id
            )
            task_result = await runner.run(
                task_config, task_input, on_message=on_message
            )
            _total_tokens_in += task_result.tokens_in
            _total_tokens_out += task_result.tokens_out
            _total_cost_usd += task_result.cost_usd or 0.0
            _total_agent_calls += 1

            if not task_result.success:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=task_result.error or "task_agent failed",
                )
                return _usage_dict(
                    "failed",
                    turn,
                    error=task_result.error or "task_agent failed",
                )

            # Parse and record runs
            runs = parse_run_records(task_result.text_output)
            for run in runs:
                append_run(project_dir, experiment_id, run)
            if runs:
                progress("result", f"Recorded {len(runs)} run(s)")

            # Register methods in project registry and update leaderboard
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

                # Update leaderboard — determine primary metric and direction
                if run.metrics:
                    primary_metric, direction = _detect_primary_metric(run.metrics)
                    if primary_metric:
                        try:
                            update_leaderboard(
                                project_dir,
                                method=run.method,
                                metrics=run.metrics,
                                run_id=run.run_id,
                                params=run.params,
                                primary_metric=primary_metric,
                                direction=direction,
                                experiment_id=experiment_id,
                            )
                        except Exception as exc:
                            logger.warning("Leaderboard update failed: %s", exc)

            # --- evaluator ---
            progress("agent", "Evaluator — scoring results")
            eval_role = registry.get("evaluator")
            if eval_role is None:
                fail_session(
                    project_dir, experiment_id, error="evaluator role not found"
                )
                return _usage_dict(
                    "failed",
                    turn,
                    error="evaluator role not found",
                )

            eval_config = eval_role.build_config(
                project_dir=project_dir, experiment_id=experiment_id
            )
            eval_input = summarize_task_output(task_result.text_output)
            eval_result = await runner.run(
                eval_config, eval_input, on_message=on_message
            )
            _total_tokens_in += eval_result.tokens_in
            _total_tokens_out += eval_result.tokens_out
            _total_cost_usd += eval_result.cost_usd or 0.0
            _total_agent_calls += 1

            if not eval_result.success:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=eval_result.error or "evaluator failed",
                )
                return _usage_dict(
                    "failed",
                    turn,
                    error=eval_result.error or "evaluator failed",
                )

            evaluation = parse_evaluation(eval_result.text_output)
            if evaluation and evaluation.get("criteria_met"):
                progress("result", "Criteria met!")

                # Optionally ask advisor to review criteria before completing
                if review_criteria:
                    progress(
                        "agent",
                        "Advisor agent — reviewing criteria",
                    )
                    review_role = registry.get("advisor_agent")
                    if review_role is not None:
                        review_prompt = (
                            "The evaluator says criteria are met. "
                            "Review the current criteria and results. "
                            "Should the criteria be updated to be more "
                            "ambitious, or are they appropriate? If you "
                            "recommend updating criteria, include a "
                            "criteria_update in your response. If the "
                            "criteria are appropriate, confirm completion."
                        )
                        review_config = review_role.build_config(
                            project_dir=project_dir,
                            experiment_id=experiment_id,
                        )
                        review_result = await runner.run(
                            review_config,
                            f"{eval_result.text_output}\n\n{review_prompt}",
                            on_message=on_message,
                        )
                        _total_tokens_in += review_result.tokens_in
                        _total_tokens_out += review_result.tokens_out
                        _total_cost_usd += review_result.cost_usd or 0.0
                        _total_agent_calls += 1
                        if review_result.success:
                            review_suggestions = parse_suggestions(
                                review_result.text_output
                            )
                            if review_suggestions and review_suggestions.get(
                                "criteria_update"
                            ):
                                from urika.core.criteria import (
                                    append_criteria,
                                )

                                update = review_suggestions["criteria_update"]
                                append_criteria(
                                    project_dir,
                                    update.get("criteria", {}),
                                    set_by="advisor_agent",
                                    turn=turn,
                                    rationale=update.get("rationale", ""),
                                )
                                progress(
                                    "result",
                                    "Criteria updated — continuing",
                                )
                                # Don't complete — continue the loop
                                continue

                complete_session(project_dir, experiment_id)
                report_usage = await _generate_reports(
                    project_dir,
                    experiment_id,
                    progress,
                    runner=runner,
                    on_message=on_message,
                )
                _total_tokens_in += report_usage.get("tokens_in", 0)
                _total_tokens_out += report_usage.get("tokens_out", 0)
                _total_cost_usd += report_usage.get("cost_usd", 0.0)
                _total_agent_calls += report_usage.get("agent_calls", 0)
                _print_run_summary(project_dir, experiment_id, progress)
                return _usage_dict("completed", turn)

            # --- advisor_agent ---
            progress("agent", "Advisor agent — proposing next steps")
            suggest_role = registry.get("advisor_agent")
            if suggest_role is None:
                fail_session(
                    project_dir,
                    experiment_id,
                    error="advisor_agent role not found",
                )
                return _usage_dict(
                    "failed",
                    turn,
                    error="advisor_agent role not found",
                )

            # Check for queued user input
            user_inject = ""
            if get_user_input is not None:
                try:
                    user_inject = get_user_input()
                except Exception as exc:
                    logger.warning("User input retrieval failed: %s", exc)

            # Pass evaluator output + any user input to advisor
            advisor_prompt = eval_result.text_output
            if user_inject:
                advisor_prompt = f"User instruction: {user_inject}\n\n{advisor_prompt}"

            suggest_config = suggest_role.build_config(
                project_dir=project_dir, experiment_id=experiment_id
            )
            suggest_result = await runner.run(
                suggest_config, advisor_prompt, on_message=on_message
            )
            _total_tokens_in += suggest_result.tokens_in
            _total_tokens_out += suggest_result.tokens_out
            _total_cost_usd += suggest_result.cost_usd or 0.0
            _total_agent_calls += 1

            if not suggest_result.success:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=suggest_result.error or "advisor_agent failed",
                )
                return _usage_dict(
                    "failed",
                    turn,
                    error=suggest_result.error or "advisor_agent failed",
                )

            suggestions = parse_suggestions(suggest_result.text_output)

            # Update criteria if suggestion agent proposed changes
            if suggestions and suggestions.get("criteria_update"):
                from urika.core.criteria import append_criteria

                update = suggestions["criteria_update"]
                append_criteria(
                    project_dir,
                    update.get("criteria", {}),
                    set_by="advisor_agent",
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
                json.dumps(suggestion_data, indent=2) + "\n",
                encoding="utf-8",
            )

            # Build next task prompt from suggestions, preserving knowledge context
            if suggestions:
                task_prompt = json.dumps(suggestions)
            else:
                task_prompt = "Continue the experiment with a different approach."
            # Re-inject knowledge context so it persists across turns
            if knowledge_summary:
                task_prompt = knowledge_summary + "\n\n" + task_prompt

            update_turn(project_dir, experiment_id)

        except Exception as exc:
            fail_session(project_dir, experiment_id, error=str(exc))
            return _usage_dict("failed", turn, error=str(exc))

    # Reached max_turns without criteria being met
    complete_session(project_dir, experiment_id)
    report_usage = await _generate_reports(
        project_dir, experiment_id, progress, runner=runner, on_message=on_message
    )
    _total_tokens_in += report_usage.get("tokens_in", 0)
    _total_tokens_out += report_usage.get("tokens_out", 0)
    _total_cost_usd += report_usage.get("cost_usd", 0.0)
    _total_agent_calls += report_usage.get("agent_calls", 0)
    _print_run_summary(project_dir, experiment_id, progress)
    return _usage_dict("completed", max_turns)
