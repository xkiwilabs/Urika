"""Interactive builder-agent loop — runtime-agnostic core.

Used by:
- ``urika new`` (CLI) — wrapped by
  ``urika.cli.project_new._run_builder_agent_loop`` which injects
  prompt_toolkit-based ``ask_user`` and stdout / ThinkingPanel
  ``emit`` callbacks.
- Dashboard ``POST /api/projects/{name}/builder/start`` (planned
  v0.4.5 Track 1) — injects async-queue-based ``ask_user`` and SSE
  ``emit`` callbacks.

The function itself is UI-agnostic: it asks clarifying questions
via ``ask_user`` and reports progress / errors / partial results
via ``emit``. Callers handle rendering and timing.

Pre-v0.4.5 the body of this function lived in
``urika.cli.project_new._run_builder_agent_loop`` and was CLI-only
(used ``click.echo``, ``interactive_prompt``, ``ThinkingPanel``,
``Spinner`` directly + wrapped every agent call in
``asyncio.run``). The extraction is the v0.4.5 parity-track work
that unblocks the dashboard's interactive new-project wizard.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

logger = logging.getLogger(__name__)


EventKind = Literal[
    "step",  # one-line progress message: payload {"text": str}
    "phase",  # switched to a new agent: payload {"agent": str, "activity": str}
    "model",  # agent's model name observed: payload {"model": str}
    "tool_use",  # agent invoked a tool: payload {"tool": str, "detail": str}
    "thinking",  # agent is thinking with phrase: payload {"phrase": str}
    "error",  # recoverable error / early exit: payload {"message": str}
    "agent_text",  # raw agent output to render: payload {"text": str}
    "question",  # waiting for user answer (dashboard mirror of ask_user call):
    # payload {"text": str, "options": list[str], "is_terminal_choice": bool}.
    # NOT emitted by the core itself — produced by adapter layers
    # (e.g. the dashboard wizard) that need a stream-visible record
    # of the question for their UI. The CLI doesn't emit it.
    "done",  # whole loop completed: payload {"suggestions": dict | None}
]


@dataclass
class BuilderEvent:
    """A single progress / output event from the builder loop."""

    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuilderQuestion:
    """A question the loop wants the user to answer.

    Free-text by default. If ``options`` is non-empty, the loop
    expects the answer to be exactly one of the listed strings
    (callers may render that as a numbered menu or a button row).
    ``is_terminal_choice`` flags the final "looks good / refine /
    abort" prompt so wizard UIs can render it as a decision row
    rather than a free-text turn.
    """

    text: str
    options: list[str] = field(default_factory=list)
    is_terminal_choice: bool = False


# Callback signatures.
AskUser = Callable[[BuilderQuestion], Awaitable[str]]
Emit = Callable[[BuilderEvent], None]

# Answers that mean "skip this question" — mirrors the Phase 1
# clarifying-loop vocabulary ("done") plus the obvious synonyms.
_SKIP_ANSWERS = {"", "done", "skip"}


def _match_option(answer: str, options: list[tuple[str, str]]) -> str:
    """Map a free-form answer onto one of ``options`` (value, label) pairs.

    Accepts the 1-based number, the stored value, the full label, or an
    unambiguous label prefix. Anything unrecognised — including the skip
    vocabulary — returns ``""`` (the preference stays unset). Callers
    render the labels; users may type a number, the label, or anything."""
    a = answer.strip().lower()
    if a in _SKIP_ANSWERS:
        return ""
    for i, (value, label) in enumerate(options, 1):
        if a == str(i) or a == value or a == label.lower():
            return value
    prefix_matches = [v for v, label in options if label.lower().startswith(a)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return ""


class BuilderAborted(Exception):
    """Raised by ``ask_user`` (or by the loop on a terminal "Abort")
    to stop the builder loop cleanly. The caller is expected to roll
    back / not register the partially-built project."""


async def run_builder_loop(
    builder: object,
    scan_result: object,
    data_summary: object,
    description: str,
    question: str,
    *,
    ask_user: AskUser,
    emit: Emit,
    extra_profiles: dict[str, Any] | None = None,
    max_questions: int = 10,
) -> dict | None:
    """Run the interactive builder loop with injectable I/O.

    Phases:
      1. Clarifying questions (up to ``max_questions`` rounds via
         the ``project_builder`` agent).
      2. Advisor: produces structured suggestions for first experiments.
      3. Planning: drafts a plan from those suggestions.
      4. User refinement: user accepts, refines, or aborts.

    Returns the final suggestions dict (or ``None`` if no suggestions
    were produced). On abort, raises ``BuilderAborted``.
    Token/cost usage is persisted to
    ``<project>/.urika/usage.json`` regardless of exit path.
    """
    from urika.agents.registry import AgentRegistry
    from urika.agents.runner_routing import runner_for_project
    from urika.core.builder_prompts import (
        build_feasibility_prompt,
        build_planning_prompt,
        build_scoping_prompt,
        build_suggestion_prompt,
    )
    from urika.orchestrator.parsing import (
        _extract_json_blocks,
        parse_suggestions,
    )

    registry = AgentRegistry()
    registry.discover()

    # Usage accumulation — pre-v0.4.4.1 the project_builder /
    # advisor / planning agent calls here were never counted, so
    # ``urika usage`` understated the cost of ``urika new``.
    usage = {"tin": 0, "tout": 0, "cost": 0.0, "calls": 0}
    t0 = _time.monotonic()
    started_iso = _dt.now(_tz.utc).isoformat()

    project_dir = getattr(
        builder, "projects_dir", Path.home() / "urika-projects"
    ) / getattr(builder, "name", "")

    # v0.7.0 Task 1.5: route via the project's runtime config (urika.toml
    # may not exist yet during initial scoping — runner_for_project
    # handles that gracefully and falls back to Claude). One runner is
    # used for project_builder + advisor + planning calls below; per-
    # agent fan-out during project creation is a future refactor (the
    # mode is "configure your project", so the model strings aren't
    # locked in yet).
    runner = runner_for_project(project_dir)

    def _record_usage() -> None:
        if usage["calls"] == 0:
            return
        try:
            from urika.core.usage import record_session

            record_session(
                project_dir,
                started=started_iso,
                ended=_dt.now(_tz.utc).isoformat(),
                duration_ms=int((_time.monotonic() - t0) * 1000),
                tokens_in=usage["tin"],
                tokens_out=usage["tout"],
                cost_usd=usage["cost"],
                agent_calls=usage["calls"],
                experiments_run=0,
            )
        except Exception as exc:  # never let usage bookkeeping break setup
            logger.warning("Builder usage record failed: %s", exc)

    def _on_msg(msg: object) -> None:
        """Per-message hook during a single agent's streaming run —
        emits ``tool_use`` / ``thinking`` / ``model`` events so the
        UI layer can update its busy indicators."""
        try:
            model = getattr(msg, "model", None)
            if model:
                emit(BuilderEvent("model", {"model": model}))
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
                        emit(
                            BuilderEvent(
                                "tool_use", {"tool": tool_name, "detail": detail}
                            )
                        )
                    else:
                        emit(BuilderEvent("thinking", {"phrase": "Thinking…"}))
        except Exception:
            pass

    async def _run_agent(cfg: object, prompt: str) -> object:
        r = await runner.run(cfg, prompt, on_message=_on_msg)
        usage["tin"] += getattr(r, "tokens_in", 0) or 0
        usage["tout"] += getattr(r, "tokens_out", 0) or 0
        usage["cost"] += getattr(r, "cost_usd", 0.0) or 0.0
        usage["calls"] += 1
        return r

    def _builder_set(method: str, *args: Any) -> None:
        """Best-effort push of loop-gathered research intent onto the
        builder — the same duck-typed channel ``set_initial_suggestions``
        uses in ``finally``. Adapter shims (e.g. the dashboard's) may not
        implement every setter; the value simply doesn't persist on that
        surface."""
        fn = getattr(builder, method, None)
        if not callable(fn):
            return
        try:
            fn(*args)
        except Exception as exc:
            logger.warning("%s failed: %s", method, exc)

    # --- Early-exit guards ---
    builder_role = registry.get("project_builder")
    if builder_role is None:
        emit(
            BuilderEvent(
                "error",
                {
                    "message": "Project builder agent not found. Skipping interactive scoping."
                },
            )
        )
        _record_usage()
        emit(BuilderEvent("done", {"suggestions": None}))
        return None

    if scan_result is None:
        emit(
            BuilderEvent(
                "error",
                {"message": "No data scanned. Skipping interactive scoping."},
            )
        )
        _record_usage()
        emit(BuilderEvent("done", {"suggestions": None}))
        return None

    answers: dict[str, str] = {}
    context = ""
    suggestions: dict | None = None
    suggest_prompt = ""
    suggest_config: object = None
    plan_config: object = None

    emit(
        BuilderEvent(
            "step",
            {"text": "The project builder will ask questions to scope the project."},
        )
    )
    emit(
        BuilderEvent(
            "phase",
            {"agent": "project_builder", "activity": "Scoping the project"},
        )
    )

    try:
        # --- Phase 0: Question feasibility check (best-effort) ---
        # One agent call sanity-checks the research question against the
        # scanned data BEFORE the clarifying loop spends the user's time
        # scoping an unanswerable question. Strictly best-effort: any
        # agent or parse failure skips the step — feasibility must never
        # block project creation.
        feasibility: dict[str, Any] | None = None
        if question:
            emit(
                BuilderEvent(
                    "step",
                    {"text": "Checking the research question against the data…"},
                )
            )
            try:
                feas_config = builder_role.build_config(project_dir=project_dir)
                feas_result = await _run_agent(
                    feas_config,
                    build_feasibility_prompt(question, data_summary, scan_result),
                )
                if feas_result.success:
                    for block in _extract_json_blocks(feas_result.text_output):
                        if "answerable" in block:
                            feasibility = block
                            break
            except Exception as exc:
                logger.warning("Feasibility check failed: %s", exc)
            if feasibility is None:
                emit(
                    BuilderEvent(
                        "step",
                        {"text": "Feasibility check inconclusive — continuing."},
                    )
                )

        refinement = ""
        if feasibility is not None:
            refinement = str(feasibility.get("suggested_refinement") or "").strip()
        if feasibility is not None and (
            not feasibility.get("answerable", True) or refinement
        ):
            concern = str(feasibility.get("concern") or "").strip()
            missing = [
                str(v)
                for v in (feasibility.get("missing_variables") or [])
                if str(v).strip()
            ]
            lines: list[str] = []
            if not feasibility.get("answerable", True):
                lines.append(
                    "The research question may not be answerable from this data."
                )
            if concern:
                lines.append(concern)
            if missing:
                lines.append("Possibly missing variables: " + ", ".join(missing))
            if refinement:
                lines.append(f"Suggested refinement: {refinement}")

            original_question = question
            answer = (
                await ask_user(
                    BuilderQuestion(
                        text="\n".join(lines),
                        options=[
                            "Keep my question",
                            "Use the refined question",
                            "Let me rephrase",
                        ],
                    )
                )
            ).strip()
            low = answer.lower()
            if low in ("2", "use the refined question") and refinement:
                question = refinement
            elif low in ("3", "let me rephrase"):
                rephrased = (
                    await ask_user(
                        BuilderQuestion(text="Your refined research question")
                    )
                ).strip()
                if rephrased and rephrased.lower() not in ("done", "skip"):
                    question = rephrased
            elif low in ("", "1", "keep my question", "done", "skip"):
                pass
            else:
                # Anything else is free text — the user typed their own
                # rephrasing directly instead of picking an option.
                question = answer
            if question != original_question:
                _builder_set("set_refined_question", question)

        # --- Phase 1: Clarifying questions ---
        for _ in range(max_questions):
            prompt = build_scoping_prompt(
                scan_result,
                data_summary,
                description,
                context,
                question=question,
                extra_profiles=extra_profiles,
            )
            config = builder_role.build_config(project_dir=project_dir)
            result = await _run_agent(config, prompt)

            if not result.success:
                emit(BuilderEvent("error", {"message": f"Agent error: {result.error}"}))
                break

            blocks = _extract_json_blocks(result.text_output)
            question_text: str | None = None
            options: list[str] = []
            ready = False
            for block in blocks:
                if block.get("ready"):
                    ready = True
                    break
                if "question" in block:
                    question_text = block["question"]
                    options = list(block.get("options") or [])
                    break

            if ready:
                break
            if question_text is None:
                question_text = result.text_output.strip()
                if not question_text:
                    break

            answer = await ask_user(
                BuilderQuestion(text=question_text, options=options)
            )
            if answer.strip().lower() == "done":
                break

            answers[question_text] = answer
            context += f"Q: {question_text}\nA: {answer}\n\n"

        # --- Preference elicitation (fixed questions — no agent call) ---
        # Skippable the same way Phase 1 answers are: "done" / "skip" /
        # empty leaves the preference unset and the prompts unchanged.
        approach_options = [
            (
                "statistical",
                "Statistical testing (ANOVA, regression, hypothesis tests)",
            ),
            ("predictive", "Predictive modelling (accuracy-focused ML)"),
            ("exploratory", "Exploratory (patterns, clustering, visualization)"),
            ("mixed", "Mixed"),
        ]
        approach_answer = await ask_user(
            BuilderQuestion(
                text="Analysis approach preference",
                options=[label for _, label in approach_options],
            )
        )
        analysis_approach = _match_option(approach_answer, approach_options)

        interp_options = [
            ("interpretable", "Highly interpretable (linear models, trees)"),
            ("balanced", "Balanced (ensembles, GAMs)"),
            ("max_performance", "Max performance (anything goes)"),
        ]
        interp_answer = await ask_user(
            BuilderQuestion(
                text="Model interpretability preference",
                options=[label for _, label in interp_options],
            )
        )
        interpretability = _match_option(interp_answer, interp_options)
        if analysis_approach or interpretability:
            _builder_set(
                "set_research_preferences", analysis_approach, interpretability
            )

        # --- Hypothesis decomposition offer (best-effort) ---
        # One agent call proposing 1-4 testable hypotheses; agent or parse
        # failure skips the offer silently — like the feasibility check,
        # this must never block project creation.
        hypotheses: list[str] = []
        proposed_hypotheses: list[str] = []
        try:
            hyp_parts = ["## Research Question", question, ""]
            if context:
                hyp_parts.extend(["## Previous Answers", context, ""])
            hyp_parts.append(
                "Propose 1-4 testable hypotheses decomposing this research "
                "question. Respond with ONLY "
                '{"hypotheses": ["H1: ...", "H2: ..."]}'
            )
            hyp_config = builder_role.build_config(project_dir=project_dir)
            hyp_result = await _run_agent(hyp_config, "\n".join(hyp_parts))
            if hyp_result.success:
                for block in _extract_json_blocks(hyp_result.text_output):
                    if "hypotheses" in block:
                        proposed_hypotheses = [
                            str(h).strip()
                            for h in (block.get("hypotheses") or [])
                            if str(h).strip()
                        ]
                        break
        except Exception as exc:
            logger.warning("Hypothesis proposal failed: %s", exc)
        if proposed_hypotheses:
            listing = "\n".join(f"- {h}" for h in proposed_hypotheses)
            hyp_answer = (
                await ask_user(
                    BuilderQuestion(
                        text=f"Proposed hypotheses:\n{listing}",
                        options=["Accept", "Skip"],
                    )
                )
            ).strip()
            low = hyp_answer.lower()
            if low in ("1", "accept"):
                hypotheses = proposed_hypotheses
            elif low == "2" or low in _SKIP_ANSWERS:
                hypotheses = []
            else:
                # Free text — the user wrote their own hypotheses,
                # one per line.
                hypotheses = [
                    ln.strip() for ln in hyp_answer.splitlines() if ln.strip()
                ]
            if hypotheses:
                _builder_set("set_hypotheses", hypotheses)

        preferences: dict[str, str] = {}
        if analysis_approach:
            preferences["analysis_approach"] = analysis_approach
        if interpretability:
            preferences["interpretability_level"] = interpretability

        # --- Phase 2: Advisor ---
        emit(
            BuilderEvent(
                "phase",
                {"agent": "advisor_agent", "activity": "Suggesting experiments"},
            )
        )
        suggest_role = registry.get("advisor_agent")
        if suggest_role is None:
            emit(
                BuilderEvent("error", {"message": "Advisor agent not found. Skipping."})
            )
            return None

        suggest_prompt = build_suggestion_prompt(
            description,
            data_summary,
            answers,
            preferences=preferences or None,
            hypotheses=hypotheses or None,
        )
        suggest_config = suggest_role.build_config(
            project_dir=project_dir, experiment_id=""
        )
        suggest_result = await _run_agent(suggest_config, suggest_prompt)

        if not suggest_result.success:
            emit(
                BuilderEvent(
                    "error", {"message": f"Advisor agent error: {suggest_result.error}"}
                )
            )
            return None

        suggestions = parse_suggestions(suggest_result.text_output)
        emit(BuilderEvent("agent_text", {"text": suggest_result.text_output}))

        # --- Phase 3: Planning ---
        emit(
            BuilderEvent(
                "phase",
                {"agent": "planning_agent", "activity": "Drafting plan"},
            )
        )
        plan_role = registry.get("planning_agent")
        if plan_role is None:
            emit(
                BuilderEvent(
                    "error", {"message": "Planning agent not found. Skipping."}
                )
            )
            return suggestions

        plan_prompt = build_planning_prompt(
            suggestions or {},
            description,
            data_summary,
            preferences=preferences or None,
            hypotheses=hypotheses or None,
        )
        plan_config = plan_role.build_config(project_dir=project_dir, experiment_id="")
        plan_result = await _run_agent(plan_config, plan_prompt)

        if not plan_result.success:
            emit(
                BuilderEvent(
                    "error", {"message": f"Planning agent error: {plan_result.error}"}
                )
            )
            return suggestions

        emit(BuilderEvent("agent_text", {"text": plan_result.text_output}))

        # --- Criteria co-draft ---
        # Offer the seed criteria for amendment before the final menu.
        # Free-text changes land verbatim as a ``user_amendments`` key —
        # the evaluator receives criteria as-is, so amendments reach it
        # without any numeric parsing on our side.
        from urika.core.project_builder import default_initial_criteria

        proposed_criteria = default_initial_criteria()
        rendered_lines = []
        for crit_key, crit_value in proposed_criteria.items():
            if isinstance(crit_value, dict):
                rendered = ", ".join(f"{k} = {v}" for k, v in crit_value.items())
            elif isinstance(crit_value, list):
                rendered = ", ".join(str(v) for v in crit_value)
            else:
                rendered = str(crit_value)
            rendered_lines.append(f"- {crit_key}: {rendered}")
        crit_answer = (
            await ask_user(
                BuilderQuestion(
                    text=(
                        "Proposed success criteria:\n"
                        + "\n".join(rendered_lines)
                        + "\nAccept, or describe changes?"
                    ),
                    options=["Accept", "Describe changes"],
                )
            )
        ).strip()
        final_criteria = dict(proposed_criteria)
        low = crit_answer.lower()
        if low in ("1", "accept") or low in _SKIP_ANSWERS:
            pass
        elif low in ("2", "describe changes"):
            changes = (
                await ask_user(BuilderQuestion(text="Describe the changes"))
            ).strip()
            if changes and changes.lower() not in _SKIP_ANSWERS:
                final_criteria["user_amendments"] = changes
        else:
            # Free text — the user described their changes directly.
            final_criteria["user_amendments"] = crit_answer
        _builder_set("set_initial_criteria", final_criteria)

        # --- Phase 4: User refinement loop ---
        while True:
            choice = await ask_user(
                BuilderQuestion(
                    text="What would you like to do?",
                    options=[
                        "Looks good — create the project",
                        "Refine — I have suggestions",
                        "Abort",
                    ],
                    is_terminal_choice=True,
                )
            )
            if choice == "Abort":
                raise BuilderAborted("user aborted at refinement step")
            if choice.startswith("Looks good"):
                break

            refinement = await ask_user(BuilderQuestion(text="Your suggestions"))
            if not refinement:
                continue

            emit(
                BuilderEvent(
                    "phase",
                    {"agent": "advisor_agent", "activity": "Refining suggestions"},
                )
            )
            refined_prompt = suggest_prompt + f"\n\n## User Refinement\n{refinement}"
            suggest_result = await _run_agent(suggest_config, refined_prompt)
            if not suggest_result.success:
                continue
            suggestions = parse_suggestions(suggest_result.text_output)
            emit(
                BuilderEvent(
                    "phase",
                    {"agent": "planning_agent", "activity": "Refining plan"},
                )
            )
            plan_prompt = build_planning_prompt(
                suggestions or {},
                description,
                data_summary,
                preferences=preferences or None,
                hypotheses=hypotheses or None,
            )
            plan_result = await _run_agent(plan_config, plan_prompt)
            if plan_result.success:
                emit(BuilderEvent("agent_text", {"text": plan_result.text_output}))

        return suggestions

    finally:
        # Store final suggestions on the builder so the caller's
        # workspace finalisation step picks them up. Only meaningful
        # when Phase 2 produced any — early-exit paths bail before
        # ``suggestions`` is set.
        if suggestions:
            try:
                builder.set_initial_suggestions(suggestions)
            except Exception as exc:
                logger.warning("set_initial_suggestions failed: %s", exc)
        # Persist loop-gathered research intent (refined question,
        # preferences, hypotheses, co-drafted criteria) onto the
        # already-written project. In the CLI flow
        # ``write_project()`` runs BEFORE this loop (the loop's agents
        # need the workspace + knowledge base on disk), so without this
        # re-apply the values would never reach urika.toml.
        _builder_set("apply_research_intent")
        _record_usage()
        emit(BuilderEvent("done", {"suggestions": suggestions}))
