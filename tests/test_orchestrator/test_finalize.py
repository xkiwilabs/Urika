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
            "run_id": "run-001",
            "experiment_id": "exp-001-baseline",
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
async def test_finalize_rejects_long_narration_with_late_heading(project_dir: Path):
    """Regression: the report agent (no Write tool) sometimes NARRATES
    ("I'll write… Let me read… I have successfully written…"). That prose
    contains markdown headings *later* in the text, so the old
    ``content.count("\\n#") >= 2`` guard let it clobber final-report.md.
    The narration guard must reject it; an existing report stays intact."""

    narration = (
        "I'll write a comprehensive final report for your project.\n"
        "Let me start by reading all the necessary project files.\n"
        "Now let me read the evaluation files for each experiment.\n"
        + ("I will now compose the report carefully. " * 12)
        + "\n\n## Report Structure\n\n"
        + ("The report covers the abstract and methods. " * 12)
        + "\nI have successfully written the report.\n"
    )

    class _NarrationRunner(_RoleRunner):
        async def run(self, config, prompt, *, on_message=None):  # type: ignore[override]
            if config.name == "report_agent":
                self.calls.append(config.name)
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output=narration,
                    session_id="s",
                    num_turns=1,
                    duration_ms=1,
                )
            return await super().run(config, prompt, on_message=on_message)

    report = project_dir / "projectbook" / "final-report.md"
    report.write_text("# Prior Real Report\n\nKept.\n", encoding="utf-8")
    runner = _NarrationRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    # Long narration with a *late* heading must NOT overwrite the report.
    assert report.read_text(encoding="utf-8") == "# Prior Real Report\n\nKept.\n"


@pytest.mark.asyncio
async def test_finalize_final_report_prompt_pins_response_is_report(project_dir: Path):
    """Pin the new prompt: it must tell the agent its reply IS the report
    and must NOT tell it to write the file at a path."""
    prompts: list[str] = []

    class _PromptCapturingRunner(_RoleRunner):
        async def run(self, config, prompt, *, on_message=None):  # type: ignore[override]
            if config.name == "report_agent":
                prompts.append(prompt)
            return await super().run(config, prompt, on_message=on_message)

    runner = _PromptCapturingRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    assert len(prompts) == 1
    p = prompts[0]
    assert "your reply IS the report" in p
    assert "Output ONLY" in p
    assert "`# ` heading" in p
    assert "write a comprehensive final report at projectbook/final-report.md" not in p


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
    assert not (project_dir / "methods" / "ridge_model_card.md").exists(), (
        "draft mode must not generate model cards — there are no final methods yet"
    )
    assert not (project_dir / "projectbook" / "METRICS.md").exists(), (
        "draft mode must not generate the metrics glossary"
    )
    assert not (project_dir / "projectbook" / "reproduce.ipynb").exists(), (
        "draft mode must not generate the reproduce notebook"
    )


@pytest.mark.asyncio
async def test_finalize_writes_model_cards(project_dir: Path):
    """After the finalizer writes findings.json, the deterministic
    model-card generator runs in the same sequence and writes one card
    per final method."""
    runner = _RoleRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    card = project_dir / "methods" / "ridge_model_card.md"
    assert card.exists(), "finalize must generate a model card per final method"
    body = card.read_text(encoding="utf-8")
    assert "r2=0.41" in body
    assert "Does X predict Y?" in body


@pytest.mark.asyncio
async def test_finalize_writes_metrics_glossary(project_dir: Path):
    """The deterministic METRICS.md generator runs in the same
    finalize sequence as the model cards."""
    runner = _RoleRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    glossary = project_dir / "projectbook" / "METRICS.md"
    assert glossary.exists(), "finalize must generate projectbook/METRICS.md"
    body = glossary.read_text(encoding="utf-8")
    assert "## r2" in body  # the fixture's recorded run carries r2


@pytest.mark.asyncio
async def test_finalize_writes_reproduce_notebook(project_dir: Path):
    """The deterministic reproduce.ipynb generator runs in the same
    Step-1b spot as model cards and METRICS.md."""
    nbformat = pytest.importorskip("nbformat")
    runner = _RoleRunner(project_dir)
    await finalize_project(project_dir, runner, audience="expert")
    notebook = project_dir / "projectbook" / "reproduce.ipynb"
    assert notebook.exists(), "finalize must generate projectbook/reproduce.ipynb"
    nb = nbformat.read(notebook, as_version=4)
    nbformat.validate(nb)
    code_sources = [c.source for c in nb.cells if c.cell_type == "code"]
    assert any("import numpy" in s for s in code_sources), (
        "the finalizer's method script must be embedded verbatim"
    )


@pytest.mark.asyncio
async def test_finalize_survives_reproduce_notebook_failure(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Notebook generation is best-effort — an exception must not
    block the rest of the finalize sequence."""
    import urika.core.notebook_export as notebook_export

    def _boom(*args: object, **kwargs: object) -> Path | None:
        raise RuntimeError("notebook generator exploded")

    monkeypatch.setattr(notebook_export, "write_reproduce_notebook", _boom)
    runner = _RoleRunner(project_dir)
    result = await finalize_project(project_dir, runner, audience="expert")
    assert result == {"success": True}
    assert (project_dir / "projectbook" / "final-report.md").exists(), (
        "the report step must still run after a notebook failure"
    )


@pytest.mark.asyncio
async def test_finalize_survives_metrics_glossary_failure(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """METRICS.md generation is best-effort — an exception must not
    block the rest of the finalize sequence."""
    import urika.core.metrics_glossary as metrics_glossary

    def _boom(*args: object, **kwargs: object) -> Path | None:
        raise RuntimeError("glossary generator exploded")

    monkeypatch.setattr(metrics_glossary, "write_metrics_glossary", _boom)
    runner = _RoleRunner(project_dir)
    result = await finalize_project(project_dir, runner, audience="expert")
    assert result == {"success": True}
    assert (project_dir / "projectbook" / "final-report.md").exists(), (
        "the report step must still run after a metrics-glossary failure"
    )


@pytest.mark.asyncio
async def test_finalize_integrity_validation_warns_on_missing_script(
    project_dir: Path,
):
    """Step 5 integrity validation: a findings.json final method whose
    ``script`` does not exist on disk produces a "warning" progress event
    AND a ``projectbook/.finalize-warnings.txt`` sidecar — but finalize
    still returns success (the check is WARN-only, never blocking)."""

    class _MissingScriptRunner(_RoleRunner):
        async def run(self, config, prompt, *, on_message=None):  # type: ignore[override]
            if config.name == "finalizer":
                self.calls.append(config.name)
                fp = self._proj / "projectbook" / "findings.json"
                fp.parent.mkdir(parents=True, exist_ok=True)
                # script points at a file the finalizer never wrote
                fp.write_text(
                    json.dumps(
                        {
                            "answer": "Yes.",
                            "final_methods": [
                                {
                                    "name": "ridge",
                                    "script": "methods/never_written.py",
                                    "run_id": "r1",
                                    "experiment_id": "exp-001",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output="wrote findings.json",
                    session_id="s",
                    num_turns=1,
                    duration_ms=1,
                )
            return await super().run(config, prompt, on_message=on_message)

    events: list[tuple[str, str]] = []
    runner = _MissingScriptRunner(project_dir)
    result = await finalize_project(
        project_dir,
        runner,
        on_progress=lambda e, d="": events.append((e, d)),
        audience="expert",
    )
    assert result == {"success": True}, "WARN-only validation must not block finalize"
    sidecar = project_dir / "projectbook" / ".finalize-warnings.txt"
    assert sidecar.exists(), "missing-script warning must be written to sidecar"
    assert "never_written.py" in sidecar.read_text(encoding="utf-8")
    assert any(e == "warning" and "never_written.py" in d for e, d in events), (
        "a 'warning' progress event must fire for the dangling script"
    )


@pytest.mark.asyncio
async def test_finalize_integrity_validation_skipped_in_draft(project_dir: Path):
    """Draft mode must not run integrity validation — no sidecar."""

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
    assert not (project_dir / "projectbook" / ".finalize-warnings.txt").exists()


@pytest.mark.asyncio
async def test_finalize_survives_integrity_validation_failure(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Step 5 validation is best-effort — an exception must not block
    finalize from returning success."""
    import urika.core.finalize_check as finalize_check

    def _boom(*args: object, **kwargs: object) -> list[str]:
        raise RuntimeError("validator exploded")

    monkeypatch.setattr(finalize_check, "validate_finalize_artifacts", _boom)
    runner = _RoleRunner(project_dir)
    result = await finalize_project(project_dir, runner, audience="expert")
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_finalize_survives_model_card_failure(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """Model-card generation is best-effort — an exception must not
    block the rest of the finalize sequence."""
    import urika.core.model_cards as model_cards

    def _boom(*args: object, **kwargs: object) -> list[Path]:
        raise RuntimeError("card generator exploded")

    monkeypatch.setattr(model_cards, "generate_model_cards", _boom)
    runner = _RoleRunner(project_dir)
    result = await finalize_project(project_dir, runner, audience="expert")
    assert result == {"success": True}
    assert (project_dir / "projectbook" / "final-report.md").exists(), (
        "the report step must still run after a model-card failure"
    )
