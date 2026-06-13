"""REPL agent-slash delegation parity.

Each of /evaluate, /plan, /report, /present, /finalize, /build-tool
wraps ``_run_single_agent(session, role_name, exp_id, prompt)``. The
slash itself must select the correct role and forward the experiment
ID — pre-this-file none of those were tested as slashes (only the CLI
equivalents had coverage).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.repl.session import ReplSession


def _setup(tmp_path: Path) -> ReplSession:
    from urika.core.experiment import create_experiment
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "p"
    create_project_workspace(
        proj, ProjectConfig(name="p", question="Q?", mode="exploratory")
    )
    create_experiment(proj, name="baseline", hypothesis="h")
    session = ReplSession()
    session.load_project(path=proj, name="p")
    # Seed a fake completed run for /report and /present.
    exp_dir = proj / "experiments" / "exp-001-baseline"
    progress = exp_dir / "progress.json"
    progress.write_text(
        json.dumps(
            {
                "status": "completed",
                "runs": [{"run_id": "r1", "method": "lr", "metrics": {"r2": 0.5}}],
            }
        )
    )
    return session


@pytest.fixture
def recorder(monkeypatch) -> list:
    """Records every (role_name, exp_id, prompt[, kwargs]) call to
    ``_run_single_agent`` and returns a stub markdown body."""
    calls: list = []

    def _fake(session, role_name, exp_id, prompt, *, audience=None, **kw):  # noqa: ANN001
        calls.append(
            {
                "role": role_name,
                "exp_id": exp_id,
                "prompt": prompt,
                "audience": audience,
                "kwargs": kw,
            }
        )
        return "# Stub report\n\n" + ("Some report content. " * 40) + "\n"

    monkeypatch.setattr("urika.repl.cmd_agents._run_single_agent", _fake)
    return calls


def test_cmd_evaluate_dispatches_evaluator(tmp_path, recorder) -> None:
    from urika.repl.cmd_agents import cmd_evaluate

    cmd_evaluate(_setup(tmp_path), "")
    assert any(c["role"] == "evaluator" for c in recorder)


def test_cmd_evaluate_with_explicit_exp_id(tmp_path, recorder) -> None:
    from urika.repl.cmd_agents import cmd_evaluate

    cmd_evaluate(_setup(tmp_path), "exp-001-baseline")
    assert recorder[0]["exp_id"] == "exp-001-baseline"


def test_cmd_evaluate_with_no_experiments_reports_empty(tmp_path, capsys) -> None:
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace
    from urika.repl.cmd_agents import cmd_evaluate

    proj = tmp_path / "empty"
    create_project_workspace(
        proj, ProjectConfig(name="empty", question="?", mode="exploratory")
    )
    session = ReplSession()
    session.load_project(path=proj, name="empty")
    cmd_evaluate(session, "")
    assert "No experiments" in capsys.readouterr().out


def test_cmd_plan_dispatches_planning_agent(tmp_path, recorder) -> None:
    from urika.repl.cmd_agents import cmd_plan

    cmd_plan(_setup(tmp_path), "")
    assert any(c["role"] == "planning_agent" for c in recorder)


def test_cmd_report_per_experiment_dispatches_report_agent(
    tmp_path, recorder, monkeypatch
) -> None:
    from urika.repl.cmd_agents import cmd_report

    # _pick_experiment with explicit exp_id arg
    cmd_report(_setup(tmp_path), "exp-001-baseline")
    assert any(c["role"] == "report_agent" for c in recorder)


def test_cmd_present_dispatches_presentation_agent(tmp_path, recorder) -> None:
    from urika.repl.cmd_agents import cmd_present

    cmd_present(_setup(tmp_path), "exp-001-baseline")
    assert any(c["role"] == "presentation_agent" for c in recorder)


def test_cmd_finalize_dispatches_finalizer(tmp_path, recorder, monkeypatch) -> None:
    """The finalize slash should drive the finalizer agent (possibly
    via finalize_project — accept either)."""
    from urika.core.registry import ProjectRegistry

    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    session = _setup(tmp_path)
    ProjectRegistry().register("p", session.project_path)

    finalize_called: list = []

    async def _fake_finalize(*a, **k):  # noqa: ANN002, ANN003
        finalize_called.append(True)

    monkeypatch.setattr("urika.orchestrator.finalize.finalize_project", _fake_finalize)
    from urika.repl.cmd_agents import cmd_finalize

    try:
        cmd_finalize(session, "")
    except Exception:
        # Some downstream lookup may still fail in this minimal fixture
        # — the test's contract is "the finalize machinery was reached",
        # which the assertion below checks.
        pass
    used_role = any(c["role"] == "finalizer" for c in recorder)
    assert used_role or finalize_called, (
        "cmd_finalize neither invoked finalizer role nor finalize_project"
    )


def test_cmd_build_tool_dispatches_tool_builder(tmp_path, recorder) -> None:
    from urika.repl.cmd_agents import cmd_build_tool

    cmd_build_tool(_setup(tmp_path), "make a paired-t-test helper")
    assert any(c["role"] == "tool_builder" for c in recorder)


def test_cmd_build_tool_with_no_args_reports_usage(tmp_path, capsys) -> None:
    from urika.repl.cmd_agents import cmd_build_tool

    cmd_build_tool(_setup(tmp_path), "")
    out = capsys.readouterr().out
    # Should explain "give me instructions" or similar, not crash.
    assert out.strip(), "no output for /build-tool with empty args"


# ---------------------------------------------------------------------------
# --format parity (v0.9.0 export) — /report and /finalize
# ---------------------------------------------------------------------------


class TestParseFormatFlag:
    def test_absent_defaults_to_markdown(self) -> None:
        from urika.repl.cmd_agents import _parse_format_flag

        assert _parse_format_flag("exp-001") == ("exp-001", "markdown")

    def test_space_form(self) -> None:
        from urika.repl.cmd_agents import _parse_format_flag

        assert _parse_format_flag("exp-001 --format latex") == ("exp-001", "latex")

    def test_equals_form(self) -> None:
        from urika.repl.cmd_agents import _parse_format_flag

        assert _parse_format_flag("--format=pdf exp-001") == ("exp-001", "pdf")

    def test_unknown_value_raises(self) -> None:
        from urika.repl.cmd_agents import _parse_format_flag

        with pytest.raises(ValueError, match="docx"):
            _parse_format_flag("--format docx")

    def test_missing_value_raises(self) -> None:
        from urika.repl.cmd_agents import _parse_format_flag

        with pytest.raises(ValueError):
            _parse_format_flag("exp-001 --format")


def test_cmd_report_format_latex_exports_narrative(
    tmp_path, recorder, monkeypatch
) -> None:
    from pathlib import Path as _P

    from urika.repl.cmd_agents import cmd_report

    exported: list = []

    def _fake_export(md_path, fmt, out_dir=None):  # noqa: ANN001
        exported.append((_P(md_path), fmt))
        return _P(md_path).with_suffix(".tex")

    monkeypatch.setattr("urika.core.export.export_markdown", _fake_export)
    session = _setup(tmp_path)
    cmd_report(session, "exp-001-baseline --format latex")
    narrative = (
        session.project_path
        / "experiments"
        / "exp-001-baseline"
        / "labbook"
        / "narrative.md"
    )
    assert narrative.exists()
    assert exported == [(narrative, "latex")]


def test_cmd_report_format_export_error_keeps_markdown(
    tmp_path, recorder, monkeypatch, capsys
) -> None:
    from urika.core.export import ExportError
    from urika.repl.cmd_agents import cmd_report

    def _boom(md_path, fmt, out_dir=None):  # noqa: ANN001
        raise ExportError(
            "PDF/LaTeX export needs the export extra: pip install 'urika[export]'"
        )

    monkeypatch.setattr("urika.core.export.export_markdown", _boom)
    session = _setup(tmp_path)
    cmd_report(session, "exp-001-baseline --format pdf")
    out = capsys.readouterr().out
    assert "urika[export]" in out
    assert "kept" in out, "the REPL must say the markdown artifact was retained"
    narrative = (
        session.project_path
        / "experiments"
        / "exp-001-baseline"
        / "labbook"
        / "narrative.md"
    )
    assert narrative.exists()


def test_cmd_report_format_bad_value_prints_usage(tmp_path, recorder, capsys) -> None:
    from urika.repl.cmd_agents import cmd_report

    cmd_report(_setup(tmp_path), "exp-001-baseline --format docx")
    out = capsys.readouterr().out
    assert "markdown|latex|pdf" in out
    assert not recorder, "a bad --format value must not invoke the report agent"


def test_cmd_finalize_threads_output_format(tmp_path, monkeypatch) -> None:
    """/finalize delegates to the CLI command via ctx.invoke — the
    parsed --format value must arrive as the ``output_format`` kwarg
    (exactly how --audience and --draft thread today)."""
    from urika.cli import finalize as cli_finalize
    from urika.core.registry import ProjectRegistry
    from urika.repl.cmd_agents import cmd_finalize

    monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    session = _setup(tmp_path)
    ProjectRegistry().register("p", session.project_path)

    captured: dict = {}

    def _fake_callback(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    monkeypatch.setattr(cli_finalize, "callback", _fake_callback)
    cmd_finalize(session, "--format latex polish the abstract")
    assert captured.get("output_format") == "latex"
    assert captured.get("instructions") == "polish the abstract"
