"""Planning helpers for `urika run`.

Split out of cli/run.py as part of Phase 8 refactoring. Holds the
"choose what to run" logic — both the dry-run preview and the
"determine the next experiment" flow.

These are pure helpers: no @cli.command decorators here. The ``run``
command itself stays in cli/run.py and imports from this module.
"""

from __future__ import annotations

from pathlib import Path

import click

from urika.cli._helpers import _prompt_numbered
from urika.core.experiment import create_experiment, list_experiments
from urika.core.progress import load_progress


def _print_dry_run_plan(
    *,
    project: str,
    project_path: Path,
    experiment_id: str | None,
    max_turns: int | None,
    max_experiments: int | None,
    instructions: str,
    resume: bool,
) -> None:
    """Print the planned pipeline without touching any agent or creating dirs.

    Called when ``urika run --dry-run`` is invoked. Must not import or
    instantiate AgentRunner, orchestrator, or create experiment directories.
    """
    from urika.cli_display import print_step, print_success

    click.echo()
    click.echo("  Urika dry run — no agents will be invoked.")
    click.echo()
    print_step("Project:", project)
    print_step("Path:", str(project_path))
    print_step("Experiment:", experiment_id or "(auto — will be selected at run time)")
    if max_experiments is not None:
        print_step(
            "Mode:",
            f"meta-orchestrator (up to {max_experiments} experiments)",
        )
    else:
        print_step("Mode:", "single experiment")
    if max_turns is not None:
        print_step("Max turns:", str(max_turns))
    if resume:
        print_step("Resume:", "yes")
    if instructions:
        preview = instructions[:80] + "..." if len(instructions) > 80 else instructions
        print_step("Instructions:", preview)
    click.echo()
    click.echo("  Pipeline stages (per experiment):")
    click.echo("    planning  →  task  →  evaluator  →  advisor")
    click.echo()

    # v0.4: rough cost estimate based on prior sessions in this project.
    # Useful for budgeting autonomous (--max-experiments) runs.
    try:
        from urika.core.usage import per_session_cost_distribution

        costs = per_session_cost_distribution(project_path, last_n=7)
        if costs:
            costs_sorted = sorted(costs)
            mid = costs_sorted[len(costs_sorted) // 2]
            n_runs_planned = max_experiments if max_experiments is not None else 1
            est_low = min(costs_sorted) * n_runs_planned
            est_high = max(costs_sorted) * n_runs_planned
            est_mid = mid * n_runs_planned
            click.echo(
                f"  Estimated cost: ${est_low:.2f}-${est_high:.2f} "
                f"(median ~${est_mid:.2f}; based on "
                f"{len(costs)} prior session(s) in this project)"
            )
        else:
            click.echo(
                "  Estimated cost: no prior runs to extrapolate from "
                "(hint: pass --budget USD to cap spend)"
            )
        click.echo()
    except Exception:
        # Best-effort — don't let a usage.json read failure break
        # the dry-run output.
        pass
    click.echo("  Writable directories agents will touch:")
    click.echo(f"    {project_path / 'experiments'}/         (experiment records)")
    click.echo(
        f"    {project_path / 'experiments'}/<exp>/code/  (task-agent Python code)"
    )
    click.echo(f"    {project_path / 'methods'}/            (agent-authored methods)")
    click.echo(f"    {project_path / 'progress.jsonl'}       (append-only run log)")
    click.echo(f"    {project_path / 'methods.json'}         (method registry)")
    click.echo()
    click.echo(
        "  Note: the task agent writes and executes Python under"
        " experiments/<exp>/code/."
    )
    click.echo()
    print_success("Remove --dry-run to execute.")


def _determine_next_experiment(
    project_path: Path,
    project_name: str,
    *,
    auto: bool = False,
    panel: object = None,
    instructions: str = "",
) -> str | None:
    """Determine and create the next experiment based on project state.

    Reads methods.json, criteria.json, completed experiments, and the initial
    plan to decide what should run next. If the initial plan is exhausted,
    calls the suggestion agent for next steps.
    """
    import json

    from urika.cli_display import print_step, print_success
    from urika.cli_helpers import interactive_prompt

    # Gather project state
    existing_experiments = list_experiments(project_path)
    completed = [
        e
        for e in existing_experiments
        if load_progress(project_path, e.experiment_id).get("status") == "completed"
    ]

    # Load methods registry
    methods_path = project_path / "methods.json"
    methods_summary = ""
    if methods_path.exists():
        try:
            mdata = json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            if mlist:
                methods_summary = f"{len(mlist)} methods tried. Best: "

                from urika.core.labbook import _LOWER_IS_BETTER

                def _best_metric_val(m: dict) -> float:
                    """Score a method for "best so far" ranking.

                    Pre-v0.4.2 took ``max(nums)`` over all numeric metric
                    values regardless of metric name (H11). For RMSE /
                    MAE / loss / error metrics, lower is better — the
                    naive ``max`` picked the WORST method as "best" and
                    blended scales (mixing ``r2=0.8`` with ``rmse=12.3``
                    ranked by the larger number). The fix prefers a
                    higher-is-better metric when present and inverts
                    when only lower-is-better metrics are available.
                    """
                    metrics = m.get("metrics", {})
                    nums = {
                        k: v for k, v in metrics.items() if isinstance(v, (int, float))
                    }
                    if not nums:
                        return float("-inf")
                    higher = {
                        k: v for k, v in nums.items() if k not in _LOWER_IS_BETTER
                    }
                    if higher:
                        return max(higher.values())
                    # All available metrics are lower-is-better — invert
                    # so ``max`` over the inverted values still picks
                    # the smallest (and therefore best) raw value.
                    return -min(nums.values())

                best = max(
                    (m for m in mlist if m.get("metrics")),
                    key=_best_metric_val,
                    default=None,
                )
                if best:
                    methods_summary += f"{best['name']} ({best.get('metrics', {})})"
        except (json.JSONDecodeError, KeyError):
            pass

    # Load criteria
    criteria_summary = ""
    criteria_path = project_path / "criteria.json"
    if criteria_path.exists():
        try:
            cdata = json.loads(criteria_path.read_text(encoding="utf-8"))
            versions = cdata.get("versions", [])
            if versions:
                latest = versions[-1]
                ctype = latest.get("criteria", {}).get("type", "unknown")
                criteria_summary = f"Criteria: {ctype} (v{latest['version']})"
        except (json.JSONDecodeError, KeyError):
            pass

    # Call the advisor agent when there's something for it to react to:
    # the user gave instructions, there are completed experiments to
    # build on, or this is an autonomous run (``--auto`` — the user
    # explicitly delegated method selection to the agent). For a fresh
    # interactive run with no instructions, fall through to the
    # deterministic baseline seed rather than spending API credits on a
    # cold-start advisor call.
    next_suggestion = None
    call_advisor_agent = bool(instructions) or bool(completed) or bool(auto)

    # Check for pending suggestions from remote advisor (Telegram/Slack)
    pending_path = project_path / "suggestions" / "pending.json"
    if pending_path.exists():
        try:
            data = json.loads(pending_path.read_text(encoding="utf-8"))
            suggestions = data.get("suggestions", [])
            if suggestions:
                next_suggestion = suggestions[0]
                # Consume the pending file
                pending_path.unlink(missing_ok=True)
                if not auto:
                    print_step("Using suggestion from recent advisor conversation")
        except (json.JSONDecodeError, KeyError):
            pass

    if not call_advisor_agent and next_suggestion is None:
        # First experiment, no instructions — use initial plan
        suggestions_path = project_path / "suggestions" / "initial.json"
        if suggestions_path.exists():
            try:
                data = json.loads(suggestions_path.read_text(encoding="utf-8"))
                suggestions = data.get("suggestions", [])
                if suggestions:
                    next_suggestion = suggestions[0]
            except (json.JSONDecodeError, KeyError):
                pass

    # Call suggestion agent to think about next steps — but ONLY when
    # we actually want to (user gave instructions, or there are
    # completed experiments to react to). Pre-v0.4.4.2 the advisor was
    # called unconditionally for a fresh project with no plan, even in
    # non-interactive mode — burning API credits and (worse) hanging
    # ``urika run test-proj`` in a non-TTY context (CliRunner, dashboard
    # subprocess, CI) before the loop's "no experiments and no plan"
    # message could surface. The seed-baseline branch below handles the
    # "fresh project, advisor unwanted" path deterministically.
    if next_suggestion is None and call_advisor_agent:
        try:
            import asyncio

            from urika.agents.runner import get_runner
            from urika.agents.registry import AgentRegistry

            runner = get_runner()
            registry = AgentRegistry()
            registry.discover()
            suggest_role = registry.get("advisor_agent")

            if suggest_role is not None:
                context = (
                    f"Project: {project_name}\n"
                    f"Completed experiments: {len(completed)}\n"
                    f"{methods_summary}\n{criteria_summary}\n"
                )
                if instructions:
                    context += f"\nUser instructions: {instructions}\n"
                context += "\nPropose the next experiment."

                config = suggest_role.build_config(
                    project_dir=project_path, experiment_id=""
                )

                from urika.cli_display import (
                    format_agent_output,
                    print_agent,
                    print_tool_use,
                )

                print_agent("advisor_agent")
                if panel is not None:
                    panel.update(agent="advisor_agent", activity="Analyzing…")

                def _on_msg(msg: object) -> None:
                    """Show tool use from suggestion agent."""
                    try:
                        model = getattr(msg, "model", None)
                        if model and panel is not None:
                            panel.set_model(model)
                        if hasattr(msg, "content"):
                            for block in msg.content:
                                tool_name = getattr(block, "name", None)
                                if tool_name:
                                    inp = getattr(block, "input", {}) or {}
                                    detail = ""
                                    if isinstance(inp, dict):
                                        detail = (
                                            inp.get("command", "")
                                            or inp.get("file_path", "")
                                            or inp.get("pattern", "")
                                        )
                                    print_tool_use(tool_name, detail)
                                    if panel is not None:
                                        panel.set_thinking(tool_name)
                                else:
                                    if panel is not None:
                                        panel.set_thinking("Thinking…")
                    except Exception:
                        pass

                result = asyncio.run(runner.run(config, context, on_message=_on_msg))

                if result.success:
                    from urika.orchestrator.parsing import parse_suggestions

                    parsed = parse_suggestions(result.text_output)
                    if parsed and parsed.get("suggestions"):
                        next_suggestion = parsed["suggestions"][0]
                        click.echo(format_agent_output(result.text_output))
        except Exception:
            pass

    if next_suggestion is None and not completed:
        # Brand-new project, but neither the initial plan, a pending
        # remote suggestion, nor the advisor produced anything usable —
        # don't bail with "nothing to do" and leave the user with a
        # freshly-created project that never runs. Seed a deterministic
        # baseline so the orchestrator does *some* real work. Mirrors
        # the v0.4.4 fix in ``orchestrator/meta.run_project``.
        print_step(
            "No initial plan or advisor suggestion — seeding a baseline "
            "exploratory experiment."
        )
        next_suggestion = {
            "name": "baseline",
            "method": (
                "Initial exploratory analysis: profile the dataset and fit "
                "a simple baseline model appropriate to the research question."
            ),
        }

    if next_suggestion is None:
        return None

    exp_name = next_suggestion.get("name", "auto-experiment").replace(" ", "-").lower()
    description = next_suggestion.get("method", next_suggestion.get("description", ""))
    if instructions:
        description = f"{instructions}\n\n{description}"

    # Show plan and confirm (unless --auto)
    print_step(f"Next experiment: {exp_name}")
    if description:
        short = description[:200] + "..." if len(description) > 200 else description
        click.echo(f"    {short}")
    if methods_summary:
        click.echo(f"    {methods_summary}")
    if criteria_summary:
        click.echo(f"    {criteria_summary}")

    # Refuse to auto-create-and-run an experiment when there's no
    # human at the terminal to confirm. Same guard as
    # ``cli.run_advisor._offer_to_run_advisor_suggestions`` (v0.3.2):
    # the dashboard spawns ``urika run`` non-interactively, and the
    # default option here ("Yes — create and run it") would silently
    # fire a multi-hour run if EOF fell through to options[default-1].
    import sys as _sys

    _tui_active = getattr(_sys.stdin, "_tui_bridge", False)
    if not auto and not _sys.stdin.isatty() and not _tui_active:
        return None

    if not auto:
        choice = _prompt_numbered(
            "\n  Proceed?",
            [
                "Yes — create and run it",
                "Different instructions",
                "Skip — exit",
            ],
            default=1,
        )

        if choice.startswith("Skip"):
            return None

        if choice.startswith("Different"):
            instructions = interactive_prompt("Your instructions")
            if instructions:
                description = f"{instructions}\n\n{description}"

    exp = create_experiment(
        project_path,
        name=exp_name,
        hypothesis=description[:500] if description else "",
    )
    print_success(f"Created experiment: {exp.experiment_id}")
    return exp.experiment_id


def _run_advisor_first_for_experiment(
    project_path: Path,
    project_name: str,
    experiment_id: str,
    *,
    instructions: str = "",
    panel: object = None,
) -> str:
    """Call the advisor before the orchestrator loop and merge its output
    into the existing experiment.

    Used by the dashboard handoff path: the modal pre-creates an empty
    experiment and spawns ``urika run --experiment <id> --advisor-first``.
    The advisor's output streams to stdout via the same on-message
    callback the rest of the run loop uses, so the dashboard's SSE log
    tailer captures it alongside Planning / Task / Evaluator.

    On a successful advisor pass, this helper:
    * Updates ``experiment.json`` with the suggested name + hypothesis
      (only if the existing values are empty — never overwrites a
      non-empty name).
    * Prepends the advisor's instructions to the user-supplied
      instructions (if any) and returns the merged value so the caller
      can pass the full context to the orchestrator.

    On any failure (advisor fails, no parseable suggestion, etc.) the
    experiment is left untouched and the original ``instructions`` are
    returned unchanged — the orchestrator's turn-1 name-backfill takes
    over as the safety net. The helper NEVER raises out — every path
    is caught and degrades to "return original instructions".
    """
    try:
        return _run_advisor_first_for_experiment_impl(
            project_path,
            project_name,
            experiment_id,
            instructions=instructions,
            panel=panel,
        )
    except Exception:
        # Final catch-all so a buggy advisor pass can never kill the
        # subprocess before the orchestrator loop gets to run.
        return instructions


def _run_advisor_first_for_experiment_impl(
    project_path: Path,
    project_name: str,
    experiment_id: str,
    *,
    instructions: str = "",
    panel: object = None,
) -> str:
    """Inner implementation — see ``_run_advisor_first_for_experiment``."""
    import asyncio
    import json

    from urika.cli_display import (
        format_agent_output,
        print_agent,
        print_tool_use,
    )

    # Gather project state — mirrors _determine_next_experiment.
    completed = [
        e
        for e in list_experiments(project_path)
        if load_progress(project_path, e.experiment_id).get("status") == "completed"
    ]

    methods_summary = ""
    methods_path = project_path / "methods.json"
    if methods_path.exists():
        try:
            mdata = json.loads(methods_path.read_text(encoding="utf-8"))
            mlist = mdata.get("methods", [])
            if mlist:
                methods_summary = f"{len(mlist)} methods tried. Best: "

                from urika.core.labbook import _LOWER_IS_BETTER

                def _best_metric_val(m: dict) -> float:
                    """Score a method for "best so far" ranking.

                    Pre-v0.4.2 took ``max(nums)`` over all numeric metric
                    values regardless of metric name (H11). For RMSE /
                    MAE / loss / error metrics, lower is better — the
                    naive ``max`` picked the WORST method as "best" and
                    blended scales (mixing ``r2=0.8`` with ``rmse=12.3``
                    ranked by the larger number). The fix prefers a
                    higher-is-better metric when present and inverts
                    when only lower-is-better metrics are available.
                    """
                    metrics = m.get("metrics", {})
                    nums = {
                        k: v for k, v in metrics.items() if isinstance(v, (int, float))
                    }
                    if not nums:
                        return float("-inf")
                    higher = {
                        k: v for k, v in nums.items() if k not in _LOWER_IS_BETTER
                    }
                    if higher:
                        return max(higher.values())
                    # All available metrics are lower-is-better — invert
                    # so ``max`` over the inverted values still picks
                    # the smallest (and therefore best) raw value.
                    return -min(nums.values())

                best = max(
                    (m for m in mlist if m.get("metrics")),
                    key=_best_metric_val,
                    default=None,
                )
                if best:
                    methods_summary += f"{best['name']} ({best.get('metrics', {})})"
        except (json.JSONDecodeError, KeyError):
            pass

    criteria_summary = ""
    criteria_path = project_path / "criteria.json"
    if criteria_path.exists():
        try:
            cdata = json.loads(criteria_path.read_text(encoding="utf-8"))
            versions = cdata.get("versions", [])
            if versions:
                latest = versions[-1]
                ctype = latest.get("criteria", {}).get("type", "unknown")
                criteria_summary = f"Criteria: {ctype} (v{latest['version']})"
        except (json.JSONDecodeError, KeyError):
            pass

    context = (
        f"Project: {project_name}\n"
        f"Completed experiments: {len(completed)}\n"
        f"{methods_summary}\n{criteria_summary}\n"
    )
    if instructions:
        context += f"\nUser instructions: {instructions}\n"
    context += "\nPropose the next experiment."

    try:
        from urika.agents.registry import AgentRegistry
        from urika.agents.runner import get_runner

        runner = get_runner()
        registry = AgentRegistry()
        registry.discover()
        suggest_role = registry.get("advisor_agent")
        if suggest_role is None:
            return instructions

        config = suggest_role.build_config(
            project_dir=project_path, experiment_id=experiment_id
        )

        print_agent("advisor_agent")
        if panel is not None:
            panel.update(agent="advisor_agent", activity="Analyzing…")

        def _on_msg(msg: object) -> None:
            try:
                model = getattr(msg, "model", None)
                if model and panel is not None:
                    panel.set_model(model)
                if hasattr(msg, "content"):
                    for block in msg.content:
                        tool_name = getattr(block, "name", None)
                        if tool_name:
                            inp = getattr(block, "input", {}) or {}
                            detail = ""
                            if isinstance(inp, dict):
                                detail = (
                                    inp.get("command", "")
                                    or inp.get("file_path", "")
                                    or inp.get("pattern", "")
                                )
                            print_tool_use(tool_name, detail)
                            if panel is not None:
                                panel.set_thinking(tool_name)
                        else:
                            if panel is not None:
                                panel.set_thinking("Thinking…")
            except Exception:
                pass

        result = asyncio.run(runner.run(config, context, on_message=_on_msg))
    except Exception:
        return instructions

    if not result.success:
        return instructions

    from urika.orchestrator.parsing import parse_suggestions

    parsed = parse_suggestions(result.text_output)
    if not parsed or not parsed.get("suggestions"):
        return instructions

    # Echo the advisor's text into the run log so the user sees the
    # suggestion alongside the streamed tool-use output.
    click.echo(format_agent_output(result.text_output))

    first = parsed["suggestions"][0]
    suggested_name = (first.get("name") or "").strip()
    suggested_hypothesis = (
        first.get("method") or first.get("description") or ""
    ).strip()
    advisor_instructions = (first.get("instructions") or "").strip()

    # Backfill experiment.json — only when the existing field is empty,
    # so we never overwrite a value the user already chose.
    exp_json_path = project_path / "experiments" / experiment_id / "experiment.json"
    if exp_json_path.exists():
        try:
            data = json.loads(exp_json_path.read_text(encoding="utf-8"))
            changed = False
            if not (data.get("name") or "").strip() and suggested_name:
                data["name"] = suggested_name
                changed = True
            if not (data.get("hypothesis") or "").strip() and suggested_hypothesis:
                data["hypothesis"] = suggested_hypothesis[:500]
                changed = True
            if changed:
                exp_json_path.write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
        except (json.JSONDecodeError, OSError):
            pass

    # Merge the advisor's instructions with the user's seed so the
    # planning agent reads both. User instructions go first so they
    # take primacy.
    parts = []
    if instructions:
        parts.append(instructions)
    if advisor_instructions:
        parts.append(advisor_instructions)
    elif suggested_hypothesis and suggested_hypothesis not in parts:
        parts.append(suggested_hypothesis)
    return "\n\n".join(parts)
