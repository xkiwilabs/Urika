"""Tests for OrchestratorLogger — tees stdout to <exp>/run.log."""

from __future__ import annotations

from pathlib import Path

from urika.orchestrator.run_log import OrchestratorLogger


def test_run_log_writes_to_file(tmp_path: Path, capsys):
    log_path = tmp_path / "run.log"
    with OrchestratorLogger(log_path):
        print("hello")
        print("world")
    content = log_path.read_text()
    assert "hello" in content
    assert "world" in content
    out = capsys.readouterr().out
    assert "hello" in out


def test_run_log_appends_not_truncates(tmp_path: Path, capsys):
    log_path = tmp_path / "run.log"
    log_path.write_text("pre-existing\n")
    with OrchestratorLogger(log_path):
        print("appended")
    content = log_path.read_text()
    assert "pre-existing" in content
    assert "appended" in content


def test_run_log_creates_parent_dirs(tmp_path: Path, capsys):
    log_path = tmp_path / "experiments" / "exp-001" / "run.log"
    assert not log_path.parent.exists()
    with OrchestratorLogger(log_path):
        print("hi")
    assert log_path.exists()
    assert "hi" in log_path.read_text()


def test_run_log_restores_stdout_on_exit(tmp_path: Path, capsys):
    import sys

    log_path = tmp_path / "run.log"
    original = sys.stdout
    with OrchestratorLogger(log_path):
        assert sys.stdout is not original
    assert sys.stdout is original


def test_run_log_restores_stdout_on_exception(tmp_path: Path, capsys):
    import sys

    log_path = tmp_path / "run.log"
    original = sys.stdout
    try:
        with OrchestratorLogger(log_path):
            print("before-raise")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert sys.stdout is original
    assert "before-raise" in log_path.read_text()
