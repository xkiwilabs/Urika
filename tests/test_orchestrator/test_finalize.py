"""Tests for the project finalize sequence (``orchestrator/finalize.py``).

``finalize_project`` runs Finalizer → Report → Presentation → README.
Most of its deliverables — ``findings.json``, ``requirements.txt``,
``reproduce.sh``, the standalone ``methods/final_*.py`` scripts — are
written by the *finalizer agent* via its Write tool, so a unit test
can't verify their content (that's what the e2e ``verify_finalize_*``
assertions are for). But the orchestrator-side bits *are* testable:

- the report-agent output is written to ``final-report.md`` iff it
  looks like a real report (``>500`` chars and ``>=2`` markdown headings);
- the presentation-agent output is rendered to
  ``final-presentation/index.html`` when it parses as slide JSON;
- the README is regenerated with the ``answer`` field from
  ``findings.json``.

These pin those guards so a refactor can't silently drop them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.agents.config import AgentConfig
from urika.agents.runner import AgentResult, AgentRunner
from urika.orchestrator.finalize import finalize_project

_FINDINGS = {
    "question": "Does X predict Y?",
    "answer": "Yes — X predicts Y with R²=0.41 in a ridge model.",
    "final_methods": [
        {
            "name": "ridge",
            "script": "methods/final_ridge.py",
            "key_metrics": {"r2": 0.41},
        }
    ],
}

_LONG_REPORT = (
    "# Abstract\n\n"
    + ("This is a substantial paragraph of report prose. " * 30)
    + "\n\n# Methods\n\nWe fit a ridge regression.\n\n# Results\n\nR²=0.41.\n"
)

_SLIDE_JSON = """\
```json
{
  "title": "Project Findings",
  "subtitle": "X predicts Y",
  "slides": [
    {"type": "bullets", "title": "Result", "bullets": ["R²=0.41 with ridge"]}
  ]
}
```
"""


class _RoleRunner(AgentRunner):
    """Returns role-appropriate output. The finalizer 'agent' also
    writes the files it's normally responsible for (findings.json), so
    the downstream report/presentation/README steps have something to
    read — exactly what the real Write-tool-using finalizer does."""

    def __init__(self, project_dir: Path):
        self._proj = project_dir
        self.calls: list[str] = []

    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: object = None
    ) -> AgentResult:
        role = config.name
        self.calls.append(role)
        text = ""
        if role == "finalizer":
            fp = self._proj / "projectbook" / "findings.json"
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps(_FINDINGS), encoding="utf-8")
            (self._proj / "methods").mkdir(exist_ok=True)
            (self._proj / "methods" / "final_ridge.py").write_text(
                "import numpy as np\n\ndef main():\n    pass\n", encoding="utf-8"
            )
            (self._proj / "requirements.txt").write_text(
                "numpy>=1.24\n", encoding="utf-8"
            )
            (self._proj / "reproduce.sh").write_text(
                "#!/usr/bin/env bash\npip install -r requirements.txt\n"
                "python methods/final_ridge.py --data data/x.csv\n",
                encoding="utf-8",
            )
            text = "Wrote findings.json, requirements.txt, reproduce.sh, methods/final_ridge.py."
        elif role == "report_agent":
            text = _LONG_REPORT
        elif role == "presentation_agent":
            text = _SLIDE_JSON
        return AgentResult(
            success=True,
            messages=[],
            text_output=text,
            session_id=f"s-{role}",
            num_turns=1,
            duration_ms=1,
        )


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "urika.toml").write_text(
        '[project]\nname = "proj"\nquestion = "Does X predict Y?"\nmode = "exploratory"\n'
        'description = ""\n\n[preferences]\naudience = "expert"\n',
        encoding="utf-8",
    )
    (proj / "methods.json").write_text(json.dumps({"methods": [{"name": "ridge"}]}))
    exp = proj / "experiments" / "exp-001"
    exp.mkdir(parents=True)
    (exp / "experiment.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "name": "baseline",
                "hypothesis": "Linear models suffice",
                "status": "completed",
            }
        )
    )
    (exp / "progress.json").write_text(
        json.dumps(
            {
                "experiment_id": "exp-001",
                "runs": [{"run_id": "r1", "method": "ridge", "metrics": {"r2": 0.41}}],
            }
        )
    )
    (exp / "artifacts").mkdir()
    (exp / "labbook").mkdir()
    (proj / "projectbook").mkdir()
    return proj


@pytest.mark.asyncio
async def test_finalize_writes_final_report_when_output_substantial(project_dir: Path):
    runner = _RoleRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    report = project_dir / "projectbook" / "final-report.md"
    assert report.exists(), (
        "a substantial report-agent output should be written to final-report.md"
    )
    body = report.read_text(encoding="utf-8")
    assert body.count("\n#") >= 2 and len(body) > 500
    assert "report_agent" in runner.calls


@pytest.mark.asyncio
async def test_finalize_skips_final_report_when_output_too_short(project_dir: Path):
    class _ShortReportRunner(_RoleRunner):
        async def run(self, config, prompt, *, on_message=None):  # type: ignore[override]
            if config.name == "report_agent":
                self.calls.append(config.name)
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output="I have written the report.",  # narration, not a report
                    session_id="s",
                    num_turns=1,
                    duration_ms=1,
                )
            return await super().run(config, prompt, on_message=on_message)

    runner = _ShortReportRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    assert not (project_dir / "projectbook" / "final-report.md").exists(), (
        "agent narration that isn't a real report (<500 chars / <2 headings) "
        "must NOT be written as final-report.md"
    )


@pytest.mark.asyncio
async def test_finalize_renders_presentation_from_slide_json(project_dir: Path):
    runner = _RoleRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    index = project_dir / "projectbook" / "final-presentation" / "index.html"
    assert index.exists(), (
        "valid slide JSON from the presentation agent must render to index.html"
    )
    assert "Project Findings" in index.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_finalize_readme_embeds_findings_answer(project_dir: Path):
    runner = _RoleRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    readme = project_dir / "README.md"
    assert readme.exists()
    assert _FINDINGS["answer"] in readme.read_text(encoding="utf-8"), (
        "README must be regenerated with the findings.json 'answer' field"
    )


@pytest.mark.asyncio
async def test_finalize_draft_mode_writes_to_draft_dir(project_dir: Path):
    """Draft mode keeps deliverables under projectbook/draft/ and does
    not touch the final-* paths or the README."""

    class _DraftRunner(_RoleRunner):
        async def run(self, config, prompt, *, on_message=None):  # type: ignore[override]
            if config.name == "finalizer":
                self.calls.append(config.name)
                fp = self._proj / "projectbook" / "draft" / "findings.json"
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(json.dumps(_FINDINGS), encoding="utf-8")
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output="draft",
                    session_id="s",
                    num_turns=1,
                    duration_ms=1,
                )
            return await super().run(config, prompt, on_message=on_message)

    runner = _DraftRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert", draft=True)
    assert (project_dir / "projectbook" / "draft" / "findings.json").exists()
    assert not (project_dir / "projectbook" / "final-report.md").exists()
    assert not (project_dir / "README.md").exists()
