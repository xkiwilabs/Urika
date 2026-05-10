"""Orchestrator loop: cycle agents through experiments.

The public entry-point (:func:`run_experiment`) lives here. Supporting
machinery is split into neighbour modules to keep this file focused on
the loop itself:

    loop_criteria  — result checking, primary-metric detection, _noop_callback
    loop_display   — console summary rendering
    loop_finalize  — post-experiment artifact generation (reports, slides)

The ``_check_result``, ``_detect_primary_metric``, ``_generate_reports``,
``_generate_presentation``, and ``_noop_callback`` names are re-exported
below so existing callers (``cli.agents``, RPC, tests) keep working
without updating their imports.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from urika.agents.config import load_runtime_config
from urika.agents.registry import AgentRegistry
from urika.agents.runner import AgentResult, AgentRunner  # noqa: F401
from urika.core.progress import append_run, load_progress
from urika.core.session import (
    complete_session,
    fail_session,  # noqa: F401 — used indirectly via loop_criteria
    pause_session,  # noqa: F401 — used indirectly via loop_criteria
    release_lock,
    resume_session,
    start_session,
    update_turn,
)
from urika.evaluation.leaderboard import update_leaderboard
from urika.orchestrator.context import summarize_task_output
from urika.orchestrator.knowledge import build_knowledge_summary
from urika.orchestrator.loop_criteria import (
    _LOWER_IS_BETTER,  # noqa: F401 — re-exported
    _PAUSABLE_ERRORS,  # noqa: F401 — re-exported
    _check_result,
    _detect_primary_metric,  # noqa: F401 — re-exported
    _noop_callback,
)
from urika.orchestrator.loop_display import _print_run_summary
from urika.orchestrator.loop_finalize import (
    _async_generate_summary,  # noqa: F401 — re-exported
    _generate_presentation,  # noqa: F401 — re-exported for cli.agents
    _generate_reports,
)
from urika.orchestrator.parsing import (
    parse_evaluation,
    parse_method_plan,
    parse_run_records,
    parse_suggestions,
)
from urika.orchestrator.pause import read_and_clear_flag

logger = logging.getLogger(__name__)


async def run_experiment(
    project_dir: Path,
    experiment_id: str,
    runner: AgentRunner,
    *,
    max_turns: int = 50,
    review_criteria: bool = False,
    resume: bool = False,
    on_progress: Callable[..., Any] | None = None,
    on_message: Callable[..., Any] | None = None,
    instructions: str = "",
    get_user_input: Callable[..., Any] | None = None,
    pause_controller: object = None,
    audience: str = "expert",
    budget_usd: float | None = None,
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
            logger.exception(
                "resume_session failed for %s/%s", project_dir, experiment_id
            )
            err = f"{type(exc).__name__}: {exc}"
            progress("phase", f"Experiment failed: {err}")
            return _usage_dict("failed", 0, error=err)

        # Use the last run's next_step as the initial task prompt, if available
        task_prompt = "Continue the experiment with a different approach."
        try:
            prev_progress = load_progress(project_dir, experiment_id)
            runs = prev_progress.get("runs", [])
            if runs:
                last_next_step = runs[-1].get("next_step", "")
                if last_next_step:
                    task_prompt = last_next_step
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            # Corrupt or missing progress file: continue with the
            # default prompt, but emit so the user knows the resume
            # didn't pick up where they left off. Pre-v0.4 this was a
            # silent ``pass`` and the user assumed continuity.
            if isinstance(exc, json.JSONDecodeError):
                logger.warning(
                    "progress.json unreadable for %s/%s; resuming with "
                    "default task prompt",
                    project_dir,
                    experiment_id,
                )
                progress(
                    "result",
                    "progress.json unreadable; resuming with default prompt",
                )
    else:
        try:
            start_session(project_dir, experiment_id, max_turns=max_turns)
        except Exception as exc:
            logger.exception(
                "start_session failed for %s/%s", project_dir, experiment_id
            )
            err = f"{type(exc).__name__}: {exc}"
            progress("phase", f"Experiment failed: {err}")
            return _usage_dict("failed", 0, error=err)
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
        # Cross-process pause/stop: the dashboard (and other out-of-
        # process callers) signal by writing to <project>/.urika/
        # pause_requested. Forward any such signal into the in-memory
        # controller so the existing checks below handle it uniformly.
        if pause_controller is not None:
            _flag = read_and_clear_flag(project_dir)
            if _flag == "stop":
                pause_controller.request_stop()
            elif _flag == "pause":
                pause_controller.request_pause()

        # Check for pause/stop request before starting this turn
        if pause_controller is not None and pause_controller.is_stop_requested():
            from urika.core.session import stop_session

            stop_session(project_dir, experiment_id, reason="Stopped remotely")
            progress("phase", f"Experiment stopped after turn {turn - 1}")
            return _usage_dict("stopped", turn - 1)
        if pause_controller is not None and pause_controller.is_pause_requested():
            pause_session(project_dir, experiment_id)
            progress("phase", f"Experiment paused after turn {turn - 1}")
            return _usage_dict("paused", turn - 1)

        # v0.4: cost-aware budget gate. Pause-and-resume rather
        # than fail — the user can `urika run --resume` after
        # raising the budget. Pre-v0.4 the only safety net was
        # Anthropic's spend cap, which only fires after the cost
        # has already accrued.
        if (
            budget_usd is not None
            and budget_usd > 0
            and _total_cost_usd >= budget_usd
        ):
            _budget_msg = (
                f"Budget ${budget_usd:.2f} reached after "
                f"${_total_cost_usd:.2f} spent in {turn - 1} turn(s). "
                "Pausing — resume with `urika run --resume` after "
                "raising the budget."
            )
            progress("result", _budget_msg)
            try:
                pause_session(project_dir, experiment_id)
            except Exception as exc:
                logger.warning(
                    "pause_session failed at budget gate: %s: %s",
                    type(exc).__name__,
                    exc,
                )
            progress("phase", f"Experiment paused (budget) after turn {turn - 1}")
            return _usage_dict("paused", turn - 1, error=_budget_msg)

        # Verify private endpoint is still reachable (hybrid/private mode)
        from urika.core.privacy import check_private_endpoint, requires_private_endpoint

        if requires_private_endpoint(project_dir):
            ep_ok, ep_msg = check_private_endpoint(project_dir)
            if not ep_ok:
                _ep_error = (
                    f"Private endpoint went offline: {ep_msg}. "
                    "Stopping to protect data privacy."
                )
                progress("result", _ep_error)
                fail_session(project_dir, experiment_id, error=_ep_error)
                progress("phase", f"Experiment failed: {_ep_error}")
                return _usage_dict("failed", turn, error=_ep_error)

        progress("turn", f"Turn {turn}/{max_turns}")
        try:
            # --- planning_agent (optional) ---
            plan_role = registry.get("planning_agent")
            if plan_role is not None:
                progress("agent", "Planning agent — designing method")
                plan_config = plan_role.build_config(
                    project_dir=project_dir, experiment_id=experiment_id
                )
                # v0.4.3 cache-reuse fix: project memory + advisor context
                # summary now flow via the per-turn user message instead
                # of being prepended to the system prompt, so the system
                # prompt stays byte-stable across sessions and the cached
                # prefix covers the full ~6KB base prompt. See
                # ``format_planning_context`` for the rationale.
                from urika.agents.roles.planning_agent import (
                    format_planning_context,
                )

                plan_user_input = (
                    format_planning_context(project_dir) + task_prompt
                )
                plan_result = await runner.run(
                    plan_config, plan_user_input, on_message=on_message
                )
                _total_tokens_in += plan_result.tokens_in
                _total_tokens_out += plan_result.tokens_out
                _total_cost_usd += plan_result.cost_usd or 0.0
                _total_agent_calls += 1

                _err = _check_result(
                    plan_result,
                    "planning_agent",
                    project_dir,
                    experiment_id,
                    progress,
                )
                if _err:
                    _status = (
                        "paused"
                        if plan_result.error_category in _PAUSABLE_ERRORS
                        else "failed"
                    )
                    if _status == "paused":
                        progress("phase", f"Experiment paused after turn {turn}")
                    else:
                        progress("phase", f"Experiment failed: {_err}")
                    return _usage_dict(_status, turn, error=_err)

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

            # --- data_agent (hybrid/private mode) ---
            if runtime_config.privacy_mode in ("hybrid", "private"):
                data_role = registry.get("data_agent")
                if data_role is None:
                    _data_error = (
                        "Data Agent not registered — cannot proceed in "
                        f"{runtime_config.privacy_mode} mode. "
                        "Raw data must be profiled locally before cloud "
                        "agents can run."
                    )
                    fail_session(project_dir, experiment_id, error=_data_error)
                    progress("phase", f"Experiment failed: {_data_error}")
                    return _usage_dict("failed", turn, error=_data_error)

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

                if not data_result.success:
                    # Data agent failure in private/hybrid mode is
                    # always a hard fail — not rate-limit related.
                    _data_error = (
                        "Data Agent failed — cannot proceed in "
                        f"{runtime_config.privacy_mode} mode. "
                        "Raw data must be profiled locally before "
                        "cloud agents can run. "
                        "Start your local model or switch to open mode."
                    )
                    fail_session(project_dir, experiment_id, error=_data_error)
                    progress("phase", f"Experiment failed: {_data_error}")
                    return _usage_dict("failed", turn, error=_data_error)

                if data_result.text_output:
                    task_input = data_result.text_output + "\n\n" + task_input

            # --- task_agent ---
            progress("agent", "Task agent — running experiment")
            task_role = registry.get("task_agent")
            if task_role is None:
                fail_session(
                    project_dir, experiment_id, error="task_agent role not found"
                )
                progress("phase", "Experiment failed: task_agent role not found")
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

            _err = _check_result(
                task_result,
                "task_agent",
                project_dir,
                experiment_id,
                progress,
            )
            if _err:
                _status = (
                    "paused"
                    if task_result.error_category in _PAUSABLE_ERRORS
                    else "failed"
                )
                if _status == "paused":
                    progress("phase", f"Experiment paused after turn {turn}")
                else:
                    progress("phase", f"Experiment failed: {_err}")
                return _usage_dict(_status, turn, error=_err)

            # Parse and record runs
            runs = parse_run_records(task_result.text_output)
            for run in runs:
                append_run(project_dir, experiment_id, run)
            if runs:
                progress("result", f"Recorded {len(runs)} run(s)")

                # v0.4.2 data-integrity check: scan the task agent's
                # method scripts for synthetic-data substitution. The
                # task_agent prompt now forbids fabricated data, but
                # the runtime check is a belt-and-braces signal so a
                # fabricated run lands a visible warning in run.log
                # + the dashboard SSE log instead of being silently
                # recorded as a real result.
                try:
                    from urika.core.data_integrity import (
                        assess_run_data_source,
                        format_suspect_warning,
                    )

                    experiment_dir = (
                        project_dir / "experiments" / experiment_id
                    )
                    project_data_paths: list[str] = []
                    try:
                        import tomllib

                        with open(
                            project_dir / "urika.toml", "rb"
                        ) as _f:
                            _cfg = tomllib.load(_f)
                        project_data_paths = list(
                            (_cfg.get("project", {}) or {}).get(
                                "data_paths", []
                            )
                            or []
                        )
                    except (OSError, tomllib.TOMLDecodeError):
                        # Best-effort; the check still runs without
                        # the data_paths basename hints.
                        pass

                    assessment = assess_run_data_source(
                        experiment_dir, project_data_paths
                    )
                    if assessment["synthetic_only"]:
                        warning = format_suspect_warning(assessment)
                        progress("warning", warning)
                        logger.warning(
                            "Synthetic-data run flagged in %s/%s: %s",
                            project_dir,
                            experiment_id,
                            assessment["synthetic_hits"],
                        )
                except Exception as exc:
                    # Detection is best-effort — never break the run
                    # loop if the scanner itself raises.
                    logger.warning(
                        "data_integrity scan failed: %s: %s",
                        type(exc).__name__,
                        exc,
                    )

            # Register methods in project registry and update leaderboard.
            # Pre-v0.4.2 the leaderboard update sat OUTSIDE this loop
            # (C3) — it referenced ``run`` after the for-loop ended,
            # so only the LAST run in a multi-run turn ever made it to
            # the leaderboard. Now register + leaderboard happen
            # together per run.
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

            # Backfill experiment.name from the first registered method
            # when the dashboard pre-created the experiment with an
            # empty name (the dashboard's "+ New experiment" flow
            # bypasses the planning-agent naming the CLI does in
            # _determine_next_experiment). Don't touch the experiment
            # ID — only the displayed name.
            if runs:
                exp_json = project_dir / "experiments" / experiment_id / "experiment.json"
                try:
                    if exp_json.exists():
                        meta = json.loads(exp_json.read_text(encoding="utf-8"))
                        if not (meta.get("name") or "").strip():
                            meta["name"] = runs[0].method.replace("_", " ").title()
                            if not (meta.get("hypothesis") or "").strip():
                                meta["hypothesis"] = runs[0].observation or ""
                            exp_json.write_text(
                                json.dumps(meta, indent=2) + "\n",
                                encoding="utf-8",
                            )
                except (OSError, ValueError, json.JSONDecodeError):
                    # Non-fatal — name backfill is cosmetic. Don't
                    # break the run if we can't update it.
                    pass

            # --- evaluator ---
            progress("agent", "Evaluator — scoring results")
            eval_role = registry.get("evaluator")
            if eval_role is None:
                fail_session(
                    project_dir, experiment_id, error="evaluator role not found"
                )
                progress("phase", "Experiment failed: evaluator role not found")
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

            _err = _check_result(
                eval_result,
                "evaluator",
                project_dir,
                experiment_id,
                progress,
            )
            if _err:
                _status = (
                    "paused"
                    if eval_result.error_category in _PAUSABLE_ERRORS
                    else "failed"
                )
                if _status == "paused":
                    progress("phase", f"Experiment paused after turn {turn}")
                else:
                    progress("phase", f"Experiment failed: {_err}")
                return _usage_dict(_status, turn, error=_err)

            evaluation = parse_evaluation(eval_result.text_output)
            if evaluation and evaluation.get("criteria_met"):
                progress("result", "Criteria met!")

                # Determine if criteria should be reviewed before completing
                should_review = review_criteria
                # In exploratory mode, always review — advisor decides if
                # the bar should be raised
                try:
                    import tomllib as _tomllib

                    _toml = project_dir / "urika.toml"
                    if _toml.exists():
                        with open(_toml, "rb") as _f:
                            _tdata = _tomllib.load(_f)
                        if (
                            _tdata.get("project", {}).get("mode", "exploratory")
                            == "exploratory"
                        ):
                            should_review = True
                except Exception:
                    pass

                # Optionally ask advisor to review criteria before completing
                if should_review:
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
                        # Inject the rolling advisor-history summary so
                        # the criteria-review advisor sees what's been
                        # discussed before deciding whether to raise the
                        # bar — same context the other advisor paths get.
                        review_input = (
                            f"{eval_result.text_output}\n\n{review_prompt}"
                        )
                        try:
                            from urika.core.advisor_memory import (
                                load_context_summary,
                            )

                            _ctx = load_context_summary(project_dir)
                            if _ctx:
                                review_input = (
                                    f"## Research Context (from previous sessions)\n\n"
                                    f"{_ctx}\n\n---\n\n{review_input}"
                                )
                        except Exception as exc:
                            logger.warning(
                                "Advisor context summary unavailable: %s", exc
                            )
                        review_result = await runner.run(
                            review_config,
                            review_input,
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
                    audience=audience,
                )
                _total_tokens_in += report_usage.get("tokens_in", 0)
                _total_tokens_out += report_usage.get("tokens_out", 0)
                _total_cost_usd += report_usage.get("cost_usd", 0.0)
                _total_agent_calls += report_usage.get("agent_calls", 0)
                _print_run_summary(project_dir, experiment_id, progress)
                progress("phase", "Experiment completed")
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
                progress("phase", "Experiment failed: advisor_agent role not found")
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

            # Pass evaluator output + any user input to advisor.
            # Inject the rolling advisor-history summary so the agent
            # sees what it (and the user) has been discussing across
            # sessions — same context the standalone advisor and the
            # meta-loop already get. Closes the inconsistency where
            # the per-turn end-of-loop advisor was the only path
            # without explicit history injection.
            advisor_prompt = eval_result.text_output
            try:
                from urika.core.advisor_memory import load_context_summary

                _ctx_summary = load_context_summary(project_dir)
                if _ctx_summary:
                    advisor_prompt = (
                        f"## Research Context (from previous sessions)\n\n"
                        f"{_ctx_summary}\n\n"
                        f"---\n\n"
                        f"{advisor_prompt}"
                    )
            except Exception as exc:
                # Summary is best-effort — never fail the turn over it.
                logger.warning("Advisor context summary unavailable: %s", exc)
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

            _err = _check_result(
                suggest_result,
                "advisor_agent",
                project_dir,
                experiment_id,
                progress,
            )
            if _err:
                _status = (
                    "paused"
                    if suggest_result.error_category in _PAUSABLE_ERRORS
                    else "failed"
                )
                if _status == "paused":
                    progress("phase", f"Experiment paused after turn {turn}")
                else:
                    progress("phase", f"Experiment failed: {_err}")
                return _usage_dict(_status, turn, error=_err)

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
            # Log the full traceback so per-turn crashes land in the
            # run.log the SSE tailer reads. Pre-v0.3.2 this branch
            # only forwarded ``str(exc)`` so a KeyError parsing an
            # evaluator block became "Experiment failed: 'criteria_met'"
            # with no traceback anywhere.
            logger.exception("Turn %d crashed", turn)
            try:
                fail_session(
                    project_dir,
                    experiment_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            except Exception as fail_exc:
                logger.warning("fail_session raised: %s", fail_exc)
            finally:
                try:
                    release_lock(project_dir, experiment_id)
                except Exception:
                    pass
            progress("phase", f"Experiment failed: {type(exc).__name__}: {exc}")
            return _usage_dict(
                "failed", turn, error=f"{type(exc).__name__}: {exc}"
            )

    # Reached max_turns without criteria being met
    complete_session(project_dir, experiment_id)
    report_usage = await _generate_reports(
        project_dir,
        experiment_id,
        progress,
        runner=runner,
        on_message=on_message,
        audience=audience,
    )
    _total_tokens_in += report_usage.get("tokens_in", 0)
    _total_tokens_out += report_usage.get("tokens_out", 0)
    _total_cost_usd += report_usage.get("cost_usd", 0.0)
    _total_agent_calls += report_usage.get("agent_calls", 0)
    _print_run_summary(project_dir, experiment_id, progress)
    progress("phase", "Experiment completed")
    return _usage_dict("completed", max_turns)
