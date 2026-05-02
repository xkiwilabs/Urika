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


# ── v0.4.1 #4: Bash timeout cap via max_method_seconds ────────────────


class TestBashTimeoutCap:
    """Regression: pre-v0.4.1 there was no Urika-controlled per-Bash-
    tool-call wall-clock cap. A deadlocked training script (infinite
    loop, stuck GPU op) could wedge an experiment for hours, since
    the bundled CLI's own default Bash timeout is ~10 min and the
    task agent's max_turns lets it retry many times.

    The fix injects ``max_method_seconds * 1000`` ms into the Bash
    tool_input via the ``can_use_tool`` callback's
    ``PermissionResultAllow.updated_input`` field. The agent sees
    its request silently capped; the SDK forwards the updated input
    to the CLI, which honours the timeout field per Anthropic's tool
    spec.
    """

    @pytest.mark.asyncio
    async def test_no_cap_when_max_method_seconds_unset(self):
        """Default behaviour (no cap configured) must not change the
        tool input — pre-v0.4.1 callers relied on the bundled CLI's
        own default."""
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["python"]), None,
            max_method_seconds=None,
        )
        result = await cb("Bash", {"command": "python -c 'pass'"}, None)
        # Plain allow — no updated_input.
        assert getattr(result, "updated_input", None) is None

    @pytest.mark.asyncio
    async def test_cap_injected_when_no_timeout_specified(self):
        """When the agent doesn't ask for a timeout, the cap becomes
        the default. This is the dominant case — the agent rarely
        sets timeout explicitly."""
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["python"]), None,
            max_method_seconds=1800,  # 30 min default
        )
        result = await cb("Bash", {"command": "python train.py"}, None)
        assert result.updated_input == {
            "command": "python train.py",
            "timeout": 1_800_000,  # 30 min in ms
        }

    @pytest.mark.asyncio
    async def test_oversized_request_clamped_down(self):
        """An agent that asks for 4 hours when the cap is 30 min gets
        clamped to 30 min — silently. The agent's intent is logged in
        its own narration, but Urika enforces the project ceiling."""
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["python"]), None,
            max_method_seconds=1800,
        )
        result = await cb(
            "Bash",
            {"command": "python train.py", "timeout": 14_400_000},  # 4h
            None,
        )
        assert result.updated_input["timeout"] == 1_800_000

    @pytest.mark.asyncio
    async def test_smaller_request_passes_through_unchanged(self):
        """An agent that asks for 10 seconds (e.g. a quick health
        check) gets 10 seconds — the cap is an upper bound, not a
        floor. Forcing every Bash to wait 30 min would make quick
        failures slow."""
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["python"]), None,
            max_method_seconds=1800,
        )
        result = await cb(
            "Bash",
            {"command": "python -c 'pass'", "timeout": 10_000},  # 10s
            None,
        )
        # Plain allow — no clamp because the request is under the cap.
        assert getattr(result, "updated_input", None) is None

    @pytest.mark.asyncio
    async def test_cap_does_not_apply_to_non_bash_tools(self):
        """The timeout cap is Bash-specific. Read / Write / Glob etc.
        don't have a timeout field worth capping."""
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(readable=[Path("/tmp")]), Path("/tmp"),
            max_method_seconds=1800,
        )
        result = await cb("Read", {"file_path": "/tmp/x"}, None)
        assert getattr(result, "updated_input", None) is None

    @pytest.mark.asyncio
    async def test_deny_path_still_overrides_cap(self):
        """A denied Bash command must still be denied — the cap path
        only affects already-allowed tools. Pre-fix concern: making
        sure the Bash-cap branch doesn't accidentally swallow denials.
        """
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["urika"]), None,
            max_method_seconds=1800,
        )
        result = await cb("Bash", {"command": "rm -rf /"}, None)
        assert hasattr(result, "message")
        assert result.message

    @pytest.mark.asyncio
    async def test_invalid_timeout_field_treated_as_missing(self):
        """If an agent (or upstream tool injection) sends a non-int
        timeout, treat it as missing and apply the cap as default
        rather than crashing inside the callback."""
        from urika.agents.permission import make_can_use_tool

        cb = make_can_use_tool(
            _policy(allowed_bash=["python"]), None,
            max_method_seconds=600,
        )
        result = await cb(
            "Bash",
            {"command": "python x.py", "timeout": "not-a-number"},
            None,
        )
        assert result.updated_input["timeout"] == 600_000


# ── v0.4.1 #4: load_max_method_seconds ────────────────────────────────


class TestLoadMaxMethodSeconds:
    def test_default_when_field_missing(self, tmp_path: Path) -> None:
        from urika.agents.config import load_max_method_seconds

        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "urika.toml").write_text(
            '[project]\nname="x"\nquestion="?"\nmode="exploratory"\n'
        )
        assert load_max_method_seconds(proj) == 1800  # 30 min default

    def test_explicit_override(self, tmp_path: Path) -> None:
        from urika.agents.config import load_max_method_seconds

        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "urika.toml").write_text(
            '[project]\nname="x"\nquestion="?"\nmode="exploratory"\n\n'
            "[preferences]\nmax_method_seconds = 7200\n"  # 2 hours
        )
        assert load_max_method_seconds(proj) == 7200

    def test_zero_or_negative_falls_back_to_default(
        self, tmp_path: Path
    ) -> None:
        """A user typing 0 (or a negative) gets the default — not no-cap.
        Letting 0 disable the cap silently would be a footgun for
        people who think they're "removing the cap"."""
        from urika.agents.config import load_max_method_seconds

        proj = tmp_path / "p"
        proj.mkdir()
        (proj / "urika.toml").write_text(
            '[project]\nname="x"\nquestion="?"\nmode="exploratory"\n\n'
            "[preferences]\nmax_method_seconds = 0\n"
        )
        assert load_max_method_seconds(proj) == 1800

    def test_no_project_dir_returns_none(self) -> None:
        """Out-of-project agent runs (e.g. orchestrator chat from the
        REPL with no project context) get None so the bundled CLI's
        own default stands."""
        from urika.agents.config import load_max_method_seconds

        assert load_max_method_seconds(None) is None

    def test_no_urika_toml_returns_none(self, tmp_path: Path) -> None:
        from urika.agents.config import load_max_method_seconds

        empty = tmp_path / "empty"
        empty.mkdir()
        assert load_max_method_seconds(empty) is None
