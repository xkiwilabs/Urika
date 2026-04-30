"""Tests for ``urika.agents.permission`` (v0.4 SecurityPolicy enforcement).

Decision-table coverage for every (tool, policy) combination the
runtime can encounter. The runtime path (``make_can_use_tool``) is
exercised at the SDK boundary; this file tests the pure-function
``_decide`` directly so the matrix is fast + deterministic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.config import SecurityPolicy


def _policy(
    *,
    writable: list[Path] | None = None,
    readable: list[Path] | None = None,
    allowed_bash: list[str] | None = None,
    blocked_bash: list[str] | None = None,
) -> SecurityPolicy:
    return SecurityPolicy(
        writable_dirs=writable or [],
        readable_dirs=readable or [],
        allowed_bash_prefixes=allowed_bash or [],
        blocked_bash_patterns=blocked_bash or [],
    )


# ── Bash tests ────────────────────────────────────────────────────────


class TestBashDecision:
    def test_allowed_prefix_passes(self):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "python train.py"},
            _policy(allowed_bash=["python", "pip"]),
            None,
        )
        assert ok

    def test_pip_allowed_passes(self):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "pip install numpy"},
            _policy(allowed_bash=["python", "pip"]),
            None,
        )
        assert ok

    def test_metacharacter_semicolon_denied(self):
        from urika.agents.permission import _decide

        ok, reason = _decide(
            "Bash",
            {"command": "urika status; ls /"},
            _policy(allowed_bash=["urika"]),
            None,
        )
        assert not ok
        assert "metacharacter" in reason

    def test_metacharacter_command_substitution_denied(self):
        from urika.agents.permission import _decide

        ok, reason = _decide(
            "Bash",
            {"command": "urika $(whoami)"},
            _policy(allowed_bash=["urika"]),
            None,
        )
        assert not ok
        assert "metacharacter" in reason

    def test_orchestrator_bash_bypass_blocked(self):
        """Pre-v0.4 string-prefix bypass — must now deny."""
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "urika ; rm -rf /"},
            _policy(allowed_bash=["urika"]),
            None,
        )
        assert not ok

    def test_blocked_pattern_wins_over_allow(self):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "git push origin main"},
            _policy(
                allowed_bash=["git"],
                blocked_bash=["git push"],
            ),
            None,
        )
        assert not ok

    def test_head_token_must_match_exact(self):
        """`bash -lc "ls"` shouldn't match a `python` allowlist."""
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "bash -lc ls"},
            _policy(allowed_bash=["python"]),
            None,
        )
        assert not ok

    def test_empty_allowlist_denies(self):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "echo hi"},
            _policy(allowed_bash=[]),
            None,
        )
        assert not ok

    def test_unparseable_quote_denied(self):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": "echo 'unterminated"},
            _policy(allowed_bash=["echo"]),
            None,
        )
        assert not ok

    def test_empty_command_denied(self):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Bash",
            {"command": ""},
            _policy(allowed_bash=["urika"]),
            None,
        )
        assert not ok


# ── Read / Glob / Grep tests ──────────────────────────────────────────


class TestReadDecision:
    def test_inside_readable_passes(self, tmp_path: Path):
        from urika.agents.permission import _decide

        f = tmp_path / "x.csv"
        f.write_text("hi", encoding="utf-8")
        ok, _ = _decide(
            "Read",
            {"file_path": str(f)},
            _policy(readable=[tmp_path]),
            None,
        )
        assert ok

    def test_outside_readable_denied(self, tmp_path: Path):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Read",
            {"file_path": "/etc/passwd"},
            _policy(readable=[tmp_path]),
            None,
        )
        assert not ok

    def test_dotdot_traversal_denied(self, tmp_path: Path):
        from urika.agents.permission import _decide

        proj = tmp_path / "proj"
        proj.mkdir()
        ok, _ = _decide(
            "Read",
            {"file_path": str(proj / ".." / ".." / "etc" / "passwd")},
            _policy(readable=[proj]),
            None,
        )
        assert not ok

    def test_symlink_outside_dir_denied(self, tmp_path: Path):
        from urika.agents.permission import _decide

        proj = tmp_path / "proj"
        outside = tmp_path / "outside"
        proj.mkdir()
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("nope", encoding="utf-8")
        link = proj / "leak"
        link.symlink_to(secret)
        ok, _ = _decide(
            "Read",
            {"file_path": str(link)},
            _policy(readable=[proj]),
            None,
        )
        # Resolution follows the symlink → resolved path is in
        # ``outside`` which isn't readable. Deny.
        assert not ok

    def test_glob_pattern_uses_path_input(self, tmp_path: Path):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Glob",
            {"pattern": str(tmp_path / "**/*.py")},
            _policy(readable=[tmp_path]),
            None,
        )
        assert ok

    def test_empty_path_short_circuits_to_allow(self):
        """Caller with no path key — let SDK reject."""
        from urika.agents.permission import _decide

        ok, _ = _decide("Read", {}, _policy(readable=[]), None)
        assert ok


# ── Write / Edit / NotebookEdit tests ─────────────────────────────────


class TestWriteDecision:
    def test_inside_writable_passes(self, tmp_path: Path):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Write",
            {"file_path": str(tmp_path / "out.csv")},
            _policy(writable=[tmp_path]),
            None,
        )
        assert ok

    def test_outside_writable_denied(self, tmp_path: Path):
        from urika.agents.permission import _decide

        proj = tmp_path / "proj"
        proj.mkdir()
        ok, _ = _decide(
            "Write",
            {"file_path": str(tmp_path / "outside.csv")},
            _policy(writable=[proj]),
            None,
        )
        assert not ok

    def test_empty_writable_dirs_denies(self, tmp_path: Path):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "Write",
            {"file_path": str(tmp_path / "x.csv")},
            _policy(writable=[]),
            None,
        )
        assert not ok

    def test_notebook_edit_uses_notebook_path(self, tmp_path: Path):
        from urika.agents.permission import _decide

        ok, _ = _decide(
            "NotebookEdit",
            {"notebook_path": str(tmp_path / "x.ipynb")},
            _policy(writable=[tmp_path]),
            None,
        )
        assert ok

    def test_edit_outside_writable_denied(self, tmp_path: Path):
        from urika.agents.permission import _decide

        proj = tmp_path / "proj"
        proj.mkdir()
        ok, _ = _decide(
            "Edit",
            {"file_path": "/etc/hosts"},
            _policy(writable=[proj]),
            None,
        )
        assert not ok


# ── Default-allow tier ────────────────────────────────────────────────


class TestDefaultAllow:
    def test_webfetch_allowed(self):
        from urika.agents.permission import _decide

        ok, _ = _decide("WebFetch", {"url": "https://example.com"}, _policy(), None)
        assert ok

    def test_mcp_tool_allowed(self):
        from urika.agents.permission import _decide

        ok, _ = _decide("mcp__some__server", {}, _policy(), None)
        assert ok

    def test_todowrite_allowed(self):
        from urika.agents.permission import _decide

        ok, _ = _decide("TodoWrite", {"items": []}, _policy(), None)
        assert ok


# ── Factory + SDK shape ───────────────────────────────────────────────


class TestMakeCanUseTool:
    @pytest.mark.asyncio
    async def test_callback_returns_allow_for_passing_decision(self):
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["urika"]),
            None,
        )
        result = await cb("Bash", {"command": "urika status"}, None)
        # PermissionResultAllow has no message field; PermissionResultDeny has one.
        # Just check it's the allow type by attribute presence.
        assert not hasattr(result, "message") or not result.message

    @pytest.mark.asyncio
    async def test_callback_returns_deny_for_failing_decision(self):
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["urika"]),
            None,
        )
        result = await cb("Bash", {"command": "urika ; rm -rf /"}, None)
        assert hasattr(result, "message")
        assert result.message
