"""Integration tests for the interactive ``urika new`` builder loop
(``cli.project_new._run_builder_agent_loop``).

This code path had essentially no automated coverage before v0.4.4.1
— it only runs when stdin is a real TTY and ``--json`` is not set, and
the e2e smoke uses ``urika new --json`` — which is exactly why three
beta-user crashes slipped through (a planning-agent JSON block with a
list-valued ``metrics`` crashing ``format_agent_output``; usage not
recorded; control chars in the question/description breaking
``urika.toml``).

These drive ``_run_builder_agent_loop`` with a scripted fake runner +
monkeypatched prompts and assert it survives the kinds of (messy but
realistic) agent output that broke it, and that it scopes the project
+ records usage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.runner import AgentResult


class _ScriptedRunner:
    """Returns role-appropriate text. ``planning_text`` lets a test
    inject a problematic method-plan block."""

    def __init__(self, planning_text: str | None = None) -> None:
        self.calls: list[str] = []
        self._planning_text = planning_text or (
            '```json\n{"method_name": "x", "steps": ["a"], '
            '"evaluation": {"strategy": "10-fold CV", "metrics": ["accuracy"]}}\n```'
        )

    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        name = config.name
        self.calls.append(name)
        if name == "project_builder":
            # Signal "ready" immediately so the clarifying-question loop
            # exits without an interactive_prompt call.
            text = '```json\n{"ready": true}\n```'
        elif name == "advisor_agent":
            text = '```json\n{"suggestions": [{"name": "rf-baseline", "method": "random forest"}]}\n```'
        elif name == "planning_agent":
            text = self._planning_text
        else:
            text = ""
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s-{name}-{len(self.calls)}",
            num_turns=1,
            duration_ms=1,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.0001,
        )


class _Builder:
    def __init__(self, projects_dir: Path, name: str) -> None:
        self.projects_dir = projects_dir
        self.name = name
        self.initial_suggestions = None

    def set_initial_suggestions(self, s) -> None:  # noqa: ANN001
        self.initial_suggestions = s


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_dir = projects_dir / "myproj"
    create_project_workspace(
        project_dir, ProjectConfig(name="myproj", question="Q?", mode="exploratory")
    )
    return projects_dir, project_dir


def _run(monkeypatch, projects_dir: Path, runner: _ScriptedRunner) -> _Builder:
    from urika.cli import project_new as pn
    from urika.core.source_scanner import ScanResult

    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: runner)
    monkeypatch.setattr(pn, "_prompt_numbered", lambda *a, **k: "Looks good — create")
    builder = _Builder(projects_dir, "myproj")
    pn._run_builder_agent_loop(
        builder,
        ScanResult(root=projects_dir / "myproj"),
        None,  # data_summary
        'a description with "quotes" and a tab\there',  # exercise display of odd text
        "Q?",
        extra_profiles=None,
    )
    return builder


@pytest.mark.parametrize(
    "planning_text, label",
    [
        # The exact shape that crashed pre-v0.4.4.1: metrics is a list.
        (
            '```json\n{"method_name": "rf", "steps": [{"step": 1, "action": "fit"}], '
            '"evaluation": {"strategy": "CV", "metrics": ["accuracy", "f1"]}}\n```',
            "list metrics",
        ),
        # Plain prose, no JSON fence.
        ("I'd run a random forest baseline first, then tune it.", "no fence"),
        # Fenced but not a method plan.
        ('```json\n{"thoughts": "still thinking"}\n```', "wrong schema"),
        # Empty output.
        ("", "empty"),
        # Steps as bare strings; evaluation as a string.
        (
            '```json\n{"method_name": "x", "steps": ["explore", "model"], '
            '"evaluation": "leave-one-subject-out CV"}\n```',
            "string evaluation, string steps",
        ),
    ],
)
def test_builder_loop_survives_messy_planning_output(
    tmp_path: Path, monkeypatch, planning_text: str, label: str
) -> None:
    projects_dir, project_dir = _make_project(tmp_path)
    runner = _ScriptedRunner(planning_text=planning_text)
    # Must not raise (pre-v0.4.4.1, "list metrics" raised TypeError and
    # the caller silently fell back to manual setup).
    builder = _run(monkeypatch, projects_dir, runner)
    # All three phases ran.
    assert runner.calls.count("project_builder") >= 1
    assert "advisor_agent" in runner.calls
    assert "planning_agent" in runner.calls
    # The advisor's suggestion was captured.
    assert builder.initial_suggestions, f"[{label}] no suggestions captured"


def test_builder_loop_records_usage_and_scopes_project(
    tmp_path: Path, monkeypatch
) -> None:
    from urika.core.usage import load_usage

    projects_dir, project_dir = _make_project(tmp_path)
    runner = _ScriptedRunner()
    _run(monkeypatch, projects_dir, runner)
    usage = load_usage(project_dir)
    assert usage["sessions"], "builder loop recorded no usage session"
    s = usage["sessions"][-1]
    assert s["agent_calls"] == len(runner.calls) >= 3
    assert s["tokens_in"] == 10 * s["agent_calls"]


def test_builder_loop_handles_clarifying_questions(tmp_path: Path, monkeypatch) -> None:
    """A non-trivial question loop: builder asks one question, the user
    answers, then the builder signals ready — and the answer reaches
    the suggestion prompt."""
    from urika.cli import project_new as pn
    from urika.core.source_scanner import ScanResult

    projects_dir, project_dir = _make_project(tmp_path)

    class _QRunner(_ScriptedRunner):
        async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
            self.calls.append(config.name)
            if config.name == "project_builder":
                # Dispatch on prompt content — the role now also receives
                # a feasibility-assessment prompt before the clarifying
                # loop (empty reply → step skipped, best-effort).
                if "Assess whether this research question" in prompt:
                    text = ""
                elif "Previous Answers" in prompt:
                    text = '```json\n{"ready": true}\n```'
                else:
                    text = '```json\n{"question": "How was the data collected?"}\n```'
            elif config.name == "advisor_agent":
                # The user's answer must have made it into the prompt.
                assert "weekly online survey" in prompt, prompt
                text = '```json\n{"suggestions": [{"name": "x", "method": "m"}]}\n```'
            elif config.name == "planning_agent":
                text = self._planning_text
            else:
                text = ""
            return AgentResult(
                success=True,
                messages=[],
                text_output=text,
                session_id="s",
                num_turns=1,
                duration_ms=1,
                tokens_in=1,
                tokens_out=1,
                cost_usd=0.0,
            )

    runner = _QRunner()
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: runner)
    monkeypatch.setattr(pn, "_prompt_numbered", lambda *a, **k: "Looks good — create")
    monkeypatch.setattr(
        "urika.cli_helpers.interactive_prompt",
        lambda *a, **k: "weekly online survey",
    )
    pn._run_builder_agent_loop(
        _Builder(projects_dir, "myproj"),
        ScanResult(root=project_dir),
        None,
        "desc",
        "Q?",
        extra_profiles=None,
    )
    # feasibility + question round + ready round.
    assert runner.calls.count("project_builder") == 3


# ---------------------------------------------------------------------------
# Research-goal upgrade: feasibility check / preferences / hypotheses /
# criteria co-drafting. These drive the runtime-agnostic core
# (``urika.core.builder_loop.run_builder_loop``) directly with the same
# scripted-runner pattern plus a recording ``ask_user``, against a REAL
# ``ProjectBuilder`` whose workspace was already written — mirroring the
# CLI ordering (``write_project()`` runs before the interactive loop, so
# loop-gathered intent only reaches disk via the post-loop re-apply).
# ---------------------------------------------------------------------------

_FEAS_NOT_ANSWERABLE = (
    '```json\n{"answerable": false, "missing_variables": ["reaction_time"], '
    '"concern": "No outcome column matches the stated question.", '
    '"suggested_refinement": "Which kinematic features predict target choice?"}\n```'
)

_REFINEMENT_OPTIONS = [
    "Keep my question",
    "Use the refined question",
    "Let me rephrase",
]


class _IntentRunner(_ScriptedRunner):
    """Scripted runner that dispatches ``project_builder`` calls on prompt
    content — the loop sends that role three different prompt shapes
    (feasibility assessment, clarifying-question scoping, hypothesis
    decomposition). Records every (agent, prompt) pair for assertions."""

    def __init__(
        self,
        *,
        feasibility_text: str = "",
        hypotheses_text: str = "",
        planning_text: str | None = None,
    ) -> None:
        super().__init__(planning_text)
        self.feasibility_text = feasibility_text
        self.hypotheses_text = hypotheses_text
        self.prompts: list[tuple[str, str]] = []

    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        self.prompts.append((config.name, prompt))
        if config.name == "project_builder":
            self.calls.append(config.name)
            if "Assess whether this research question" in prompt:
                text = self.feasibility_text
            elif "Propose 1-4 testable hypotheses" in prompt:
                text = self.hypotheses_text
            else:
                text = '```json\n{"ready": true}\n```'
            return AgentResult(
                success=True,
                messages=[],
                text_output=text,
                session_id="s",
                num_turns=1,
                duration_ms=1,
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.0001,
            )
        return await super().run(config, prompt, on_message=on_message)

    def scoping_prompts(self) -> list[str]:
        return [
            p
            for name, p in self.prompts
            if name == "project_builder"
            and "Assess whether this research question" not in p
            and "Propose 1-4 testable hypotheses" not in p
        ]

    def advisor_prompts(self) -> list[str]:
        return [p for name, p in self.prompts if name == "advisor_agent"]

    def planning_prompts(self) -> list[str]:
        return [p for name, p in self.prompts if name == "planning_agent"]


def _drive_core_loop(monkeypatch, tmp_path, runner, answers=(), *, question="Q?"):
    """Run the core loop with scripted free-text answers (terminal choice
    always accepts). Returns ``(builder, project_dir, asked)``."""
    import asyncio

    from urika.core.builder_loop import BuilderQuestion, run_builder_loop
    from urika.core.project_builder import ProjectBuilder
    from urika.core.source_scanner import ScanResult

    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: runner)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(exist_ok=True)
    builder = ProjectBuilder(
        name="myproj",
        source_path=None,
        projects_dir=projects_dir,
        description="desc",
        question=question,
        mode="exploratory",
    )
    project_dir = builder.write_project()

    asked: list[BuilderQuestion] = []
    script = list(answers)

    async def _ask(q: BuilderQuestion) -> str:
        asked.append(q)
        if q.is_terminal_choice:
            return "Looks good — create the project"
        return script.pop(0) if script else "done"

    asyncio.run(
        run_builder_loop(
            builder,
            ScanResult(root=project_dir),
            None,
            "desc",
            question,
            ask_user=_ask,
            emit=lambda e: None,
        )
    )
    return builder, project_dir, asked


def _project_block(project_dir: Path) -> dict:
    import tomllib

    with open(project_dir / "urika.toml", "rb") as f:
        return tomllib.load(f)["project"]


class TestFeasibilityCheck:
    def test_not_answerable_offers_three_options(
        self, tmp_path: Path, monkeypatch, tmp_urika_home
    ) -> None:
        runner = _IntentRunner(feasibility_text=_FEAS_NOT_ANSWERABLE)
        _, _, asked = _drive_core_loop(
            monkeypatch, tmp_path, runner, ["Keep my question"]
        )
        refinement_qs = [q for q in asked if q.options == _REFINEMENT_OPTIONS]
        assert len(refinement_qs) == 1
        # Concern + suggested refinement both surfaced in the question text.
        assert "No outcome column matches the stated question." in refinement_qs[0].text
        assert (
            "Which kinematic features predict target choice?" in refinement_qs[0].text
        )

    def test_user_picks_refinement(
        self, tmp_path: Path, monkeypatch, tmp_urika_home
    ) -> None:
        runner = _IntentRunner(feasibility_text=_FEAS_NOT_ANSWERABLE)
        _, project_dir, _ = _drive_core_loop(
            monkeypatch, tmp_path, runner, ["Use the refined question"]
        )
        refined = "Which kinematic features predict target choice?"
        # Refined question reached the written urika.toml…
        assert _project_block(project_dir)["question"] == refined
        # …and the subsequent Phase 1 scoping prompt.
        assert refined in runner.scoping_prompts()[0]

    def test_user_keeps_question(
        self, tmp_path: Path, monkeypatch, tmp_urika_home
    ) -> None:
        runner = _IntentRunner(feasibility_text=_FEAS_NOT_ANSWERABLE)
        _, project_dir, _ = _drive_core_loop(
            monkeypatch, tmp_path, runner, ["Keep my question"]
        )
        assert _project_block(project_dir)["question"] == "Q?"
        assert "Q?" in runner.scoping_prompts()[0]

    def test_user_rephrases_freetext(
        self, tmp_path: Path, monkeypatch, tmp_urika_home
    ) -> None:
        runner = _IntentRunner(feasibility_text=_FEAS_NOT_ANSWERABLE)
        _, project_dir, _ = _drive_core_loop(
            monkeypatch,
            tmp_path,
            runner,
            ["Let me rephrase", "Does grip force predict accuracy?"],
        )
        assert (
            _project_block(project_dir)["question"]
            == "Does grip force predict accuracy?"
        )

    def test_agent_garbage_skips_step(
        self, tmp_path: Path, monkeypatch, tmp_urika_home
    ) -> None:
        """Unparseable feasibility output must never block creation: the
        step is skipped, the original question survives, and the loop
        proceeds through advisor + planning."""
        runner = _IntentRunner(feasibility_text="utterly not json {{{")
        builder, project_dir, asked = _drive_core_loop(monkeypatch, tmp_path, runner)
        assert not any(q.options == _REFINEMENT_OPTIONS for q in asked)
        assert _project_block(project_dir)["question"] == "Q?"
        assert "advisor_agent" in runner.calls
        assert "planning_agent" in runner.calls
        assert builder._suggestions

    def test_answerable_question_asks_nothing(
        self, tmp_path: Path, monkeypatch, tmp_urika_home
    ) -> None:
        runner = _IntentRunner(
            feasibility_text='```json\n{"answerable": true, "missing_variables": [], '
            '"concern": "", "suggested_refinement": ""}\n```'
        )
        _, project_dir, asked = _drive_core_loop(monkeypatch, tmp_path, runner)
        assert not any(q.options == _REFINEMENT_OPTIONS for q in asked)
        assert _project_block(project_dir)["question"] == "Q?"
