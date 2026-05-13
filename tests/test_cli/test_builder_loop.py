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
        "a description with \"quotes\" and a tab\there",  # exercise display of odd text
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


def test_builder_loop_handles_clarifying_questions(
    tmp_path: Path, monkeypatch
) -> None:
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
                n = self.calls.count("project_builder")
                text = (
                    '```json\n{"question": "How was the data collected?"}\n```'
                    if n == 1
                    else '```json\n{"ready": true}\n```'
                )
            elif config.name == "advisor_agent":
                # The user's answer must have made it into the prompt.
                assert "weekly online survey" in prompt, prompt
                text = '```json\n{"suggestions": [{"name": "x", "method": "m"}]}\n```'
            elif config.name == "planning_agent":
                text = self._planning_text
            else:
                text = ""
            return AgentResult(
                success=True, messages=[], text_output=text,
                session_id="s", num_turns=1, duration_ms=1,
                tokens_in=1, tokens_out=1, cost_usd=0.0,
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
    assert runner.calls.count("project_builder") == 2
