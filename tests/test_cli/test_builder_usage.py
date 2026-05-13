"""The interactive ``urika new`` builder loop must record its token /
cost usage. Pre-v0.4.4 the project_builder / advisor / planning agent
calls there were invisible to ``urika usage``."""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.runner import AgentResult


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        self.calls += 1
        # First call (project_builder, Phase 1): signal "ready" so the
        # questions loop exits without prompting. Later calls (advisor,
        # planning) return innocuous JSON.
        if self.calls == 1:
            text = '```json\n{"ready": true}\n```'
        else:
            text = '```json\n{"suggestions": [{"name": "x", "method": "m"}], "method_name": "x", "steps": ["a"]}\n```'
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s{self.calls}",
            num_turns=1,
            duration_ms=1,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.002,
        )


class _Builder:
    def __init__(self, projects_dir: Path, name: str) -> None:
        self.projects_dir = projects_dir
        self.name = name
        self.initial_suggestions = None

    def set_initial_suggestions(self, s) -> None:  # noqa: ANN001
        self.initial_suggestions = s


def test_builder_loop_records_usage(tmp_path: Path, monkeypatch) -> None:
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace
    from urika.core.usage import load_usage
    from urika.cli import project_new as pn

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    project_dir = projects_dir / "myproj"
    create_project_workspace(
        project_dir, ProjectConfig(name="myproj", question="Q?", mode="exploratory")
    )

    fake = _FakeRunner()
    monkeypatch.setattr("urika.agents.runner.get_runner", lambda: fake)
    # Phase 4 user-refinement menu → "Looks good — create the project".
    monkeypatch.setattr(pn, "_prompt_numbered", lambda *a, **k: "Looks good — create")
    # Stub the scan/profile inputs so build_scoping_prompt is happy.
    from urika.core.source_scanner import ScanResult

    scan = ScanResult(root=project_dir)

    pn._run_builder_agent_loop(
        _Builder(projects_dir, "myproj"),
        scan,
        None,  # data_summary
        "a description",
        "Q?",
        extra_profiles=None,
    )

    usage = load_usage(project_dir)
    sessions = usage.get("sessions", [])
    assert sessions, "builder loop recorded no usage session"
    s = sessions[-1]
    assert s["agent_calls"] >= 3  # project_builder + advisor + planning
    assert s["tokens_in"] == 100 * s["agent_calls"]
    assert s["tokens_out"] == 50 * s["agent_calls"]
    assert s["cost_usd"] == pytest.approx(0.002 * s["agent_calls"], rel=1e-6)
    assert usage["totals"]["total_agent_calls"] == s["agent_calls"]
