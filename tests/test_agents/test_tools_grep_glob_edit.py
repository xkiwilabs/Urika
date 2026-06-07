"""Tests for ``urika.agents.tools.grep`` / ``glob`` / ``edit`` — shared
search and patch tools used by non-Claude adapters.

The Claude adapter uses the SDK's built-in Grep/Glob/Edit and enforces
``SecurityPolicy`` via the ``can_use_tool`` callback. The OpenAI and
Google adapters do not get that for free, so these modules wrap the
filesystem operations with the same ``SecurityPolicy`` enforcement
that mirrors ``urika.agents.permission._path_decision``.
"""

from __future__ import annotations

from pathlib import Path

from urika.agents.permission import SecurityPolicy
from urika.agents.tools.edit import edit
from urika.agents.tools.glob import glob as glob_tool
from urika.agents.tools.grep import grep


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


def test_grep_finds_pattern(tmp_path: Path):
    (tmp_path / "f.txt").write_text("foo\nbar\nfoo bar\n")
    policy = _policy(writable=[tmp_path], readable=[tmp_path])
    r = grep("foo", str(tmp_path), security=policy)
    assert r.ok is True
    assert r.output.count("foo") == 2


def test_glob_matches_pattern(tmp_path: Path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    policy = _policy(writable=[tmp_path], readable=[tmp_path])
    r = glob_tool("*.py", security=policy, project_dir=tmp_path)
    assert r.ok is True
    assert "a.py" in r.output
    assert "b.py" in r.output
    assert "c.txt" not in r.output


def test_glob_handles_absolute_pattern(tmp_path: Path):
    """Gemini agents tend to pass absolute patterns like '/home/foo/*.csv'.
    Python 3.12 Path.rglob raises NotImplementedError on absolute patterns —
    the glob tool splits root from pattern and re-validates the resolved
    root against the SecurityPolicy.
    """
    (tmp_path / "data.csv").write_text("x")
    (tmp_path / "other.txt").write_text("x")
    policy = _policy(writable=[tmp_path], readable=[tmp_path])
    abs_pattern = str(tmp_path / "*.csv")
    r = glob_tool(abs_pattern, security=policy, project_dir=tmp_path)
    assert r.ok is True, r.error
    assert "data.csv" in r.output
    assert "other.txt" not in r.output


def test_edit_replaces_string(tmp_path: Path):
    target = tmp_path / "f.txt"
    target.write_text("alpha\nbeta\ngamma\n")
    policy = _policy(writable=[tmp_path], readable=[tmp_path])
    r = edit(str(target), "beta", "BETA", security=policy)
    assert r.ok is True
    assert target.read_text() == "alpha\nBETA\ngamma\n"


def test_edit_rejects_non_unique_old_string(tmp_path: Path):
    target = tmp_path / "f.txt"
    target.write_text("foo foo")
    policy = _policy(writable=[tmp_path], readable=[tmp_path])
    r = edit(str(target), "foo", "bar", security=policy)
    assert r.ok is False
    err = (r.error or "").lower()
    assert "occurs" in err or "unique" in err
