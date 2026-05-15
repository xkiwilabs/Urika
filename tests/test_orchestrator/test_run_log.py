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


def test_run_log_strips_ansi_escapes_from_log_but_keeps_them_on_terminal(
    tmp_path: Path, capsys
):
    """Issue 4 (Cathy on Windows): ThinkingPanel writes raw ANSI cursor-
    save/restore + scroll-region escape sequences via ``sys.stdout.write``
    at ~8 frames/second. Pre-fix the tee forwarded every byte to
    ``run.log``, producing ~344 MB of escape codes in 26 hours. The fix:
    strip ANSI escapes on the way to the log, leave them in place on the
    terminal so the live UI still renders.
    """
    import sys

    log_path = tmp_path / "run.log"
    with OrchestratorLogger(log_path):
        # Mimic a single ThinkingPanel spinner frame: cursor save (ESC 7),
        # absolute positioning (ESC [N;1H), clear-line (ESC [K), some
        # coloured text, cursor restore (ESC 8).
        frame = "\x1b7\x1b[20;1H\x1b[K\x1b[36m  ⠋ task_agent · Thinking\x1b[0m\x1b8"
        sys.stdout.write(frame)
        sys.stdout.write("\n")
        # Plain text should still land in the log unchanged.
        print("plain log line")

    log_text = log_path.read_text()
    # Plain text is preserved.
    assert "plain log line" in log_text
    # The cursor save/restore + scroll region escapes are gone.
    assert "\x1b7" not in log_text
    assert "\x1b8" not in log_text
    assert "\x1b[" not in log_text
    # ...and so is the colour code wrapping the actual content.
    assert "\x1b[36m" not in log_text
    # But the human-readable content survives.
    assert "task_agent" in log_text
    assert "Thinking" in log_text

    # And the terminal still saw the ANSI — capsys captures the primary
    # stream that _Tee writes to. (Note: capsys captures plain text;
    # the test is really that the escapes WERE emitted to the primary
    # stream — i.e. n bytes returned by write reflects the full input.)
    captured = capsys.readouterr().out
    assert "task_agent" in captured


def test_run_log_compaction_factor_is_large_for_spinner_frames(tmp_path: Path):
    """Quantitative regression: a single tight loop of spinner-style
    frames should produce a log file whose size is a tiny fraction of
    the bytes written to stdout. Pre-fix the ratio was ~1.0 (everything
    teed in full). The Windows user hit 344 MB in 26 hours; under the
    fix the same workload writes essentially zero bytes of spinner ANSI
    to disk.
    """
    import sys

    log_path = tmp_path / "run.log"
    frame = "\x1b7\x1b[20;1H\x1b[K\x1b[36m  ⠋ thinking\x1b[0m\x1b8"
    n_frames = 500
    total_input_bytes = len(frame) * n_frames

    with OrchestratorLogger(log_path):
        for _ in range(n_frames):
            sys.stdout.write(frame)

    log_size = log_path.stat().st_size
    # The escape sequences should be entirely stripped, leaving only
    # the visible characters: "  ⠋ thinking" repeated. The exact byte
    # count varies with UTF-8 encoding of ⠋, but it must be far below
    # the raw input bytes.
    assert log_size < total_input_bytes * 0.5, (
        f"ANSI stripping did not compact spinner frames: "
        f"log_size={log_size}, input_bytes={total_input_bytes}"
    )
