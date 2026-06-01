"""Tests for ``urika.agents.tools.read`` / ``write`` — shared file I/O
tools used by non-Claude adapters.

The Claude adapter uses the SDK's built-in Read/Write and enforces
``SecurityPolicy`` via the ``can_use_tool`` callback. The OpenAI and
Google adapters do not get that for free, so these modules wrap
``Path.read_text`` / ``write_text`` with the same ``SecurityPolicy``
enforcement that mirrors ``urika.agents.permission._path_decision``.
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.permission import SecurityPolicy
from urika.agents.tools.read import read
from urika.agents.tools.write import write


def _policy(
    *,
    writable: list[Path] | None = None,
    readable: list[Path] | None = None,
) -> SecurityPolicy:
    return SecurityPolicy(
        writable_dirs=writable or [],
        readable_dirs=readable or [],
        allowed_bash_prefixes=[],
        blocked_bash_patterns=[],
    )


def test_write_then_read_round_trip(tmp_path: Path):
    policy = _policy(writable=[tmp_path], readable=[tmp_path])
    target = tmp_path / "hello.txt"
    w = write(str(target), "hello world", security=policy)
    assert w.ok is True
    r = read(str(target), security=policy)
    assert r.ok is True
    assert r.output == "hello world"


def test_write_outside_writable_dir_rejected(tmp_path: Path):
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    policy = _policy(writable=[ok_dir], readable=[])
    result = write(str(tmp_path / "elsewhere" / "x.txt"), "x", security=policy)
    assert result.ok is False
    # ``_path_decision`` emits "write path outside allowed dirs: ...".
    # We assert the stable substring so the wording can evolve without
    # silently breaking this contract.
    assert "outside allowed dirs" in (result.error or "")
