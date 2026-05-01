"""Regression tests for Windows cp1252 stdout encoding.

Pre-fix, ``urika`` would crash on Windows the first time it tried to
print a box-drawing char (e.g. ``╭`` in ``print_header``) because
Python's stdout there defaults to ``cp1252`` which doesn't encode
those glyphs:

    UnicodeEncodeError: 'charmap' codec can't encode characters in
    position 2-3: character maps to <undefined>

The fix lives in ``urika.cli._base._ensure_utf8_streams`` which
reconfigures stdout/stderr to UTF-8 with ``errors="replace"`` at
import time.
"""

from __future__ import annotations

import io
import sys


class _Cp1252Stream(io.TextIOWrapper):
    """A TextIOWrapper that mimics Python's Windows console default.

    Real Windows ``sys.stdout`` is a ``TextIOWrapper`` over a binary
    buffer with ``encoding='cp1252'`` and a ``reconfigure`` method.
    We wrap a real ``BytesIO`` here so ``reconfigure`` actually works
    end-to-end (just like in production).
    """

    def __init__(self) -> None:
        super().__init__(io.BytesIO(), encoding="cp1252", line_buffering=True)


def test_ensure_utf8_streams_reconfigures_cp1252_stdout(monkeypatch) -> None:
    """When stdout claims cp1252, the helper must flip it to UTF-8."""
    fake_stdout = _Cp1252Stream()
    fake_stderr = _Cp1252Stream()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    assert fake_stdout.encoding.lower() == "cp1252"
    assert fake_stderr.encoding.lower() == "cp1252"

    from urika.cli._base import _ensure_utf8_streams

    _ensure_utf8_streams()

    assert fake_stdout.encoding.lower().replace("-", "") == "utf8"
    assert fake_stderr.encoding.lower().replace("-", "") == "utf8"


def test_box_drawing_chars_no_longer_crash_after_reconfigure(monkeypatch) -> None:
    """End-to-end: a print() with the same chars urika emits in
    print_header() must not raise UnicodeEncodeError on a cp1252
    stream after the helper runs.
    """
    fake_stdout = _Cp1252Stream()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    # Pre-reconfigure: writing the offending chars raises.
    import pytest

    with pytest.raises(UnicodeEncodeError):
        print("╭─╮")

    from urika.cli._base import _ensure_utf8_streams

    _ensure_utf8_streams()

    # Post-reconfigure: same chars go through cleanly.
    print("╭─╮")  # ╭─╮
    sys.stdout.flush()
    written = fake_stdout.buffer.getvalue().decode("utf-8")
    assert "╭─╮" in written


def test_ensure_utf8_streams_is_noop_on_utf8(monkeypatch) -> None:
    """If stdout is already UTF-8 (Linux/macOS, modern Windows
    Terminal), the helper must not call reconfigure — that's the
    cheap path the most users take.
    """
    fake_stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    calls: list[tuple] = []

    def _record_reconfigure(*args, **kwargs) -> None:
        calls.append((args, kwargs))

    fake_stdout.reconfigure = _record_reconfigure  # type: ignore[method-assign]
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    # stderr left as-is; helper iterates both streams independently.

    from urika.cli._base import _ensure_utf8_streams

    _ensure_utf8_streams()

    assert calls == [], "should not reconfigure a stream that's already UTF-8"


def test_ensure_utf8_streams_survives_missing_reconfigure(monkeypatch) -> None:
    """Older or wrapped streams (e.g. some test harnesses) lack
    ``reconfigure``. The helper must skip them silently rather than
    refusing to start the CLI.
    """

    class _StreamWithoutReconfigure:
        encoding = "cp1252"

    monkeypatch.setattr(sys, "stdout", _StreamWithoutReconfigure())
    monkeypatch.setattr(sys, "stderr", _StreamWithoutReconfigure())

    from urika.cli._base import _ensure_utf8_streams

    # Must not raise.
    _ensure_utf8_streams()
