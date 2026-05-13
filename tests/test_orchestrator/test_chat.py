"""Tests for ``OrchestratorChat`` — the conversational orchestrator.

This is the conversational entry-point for both the TUI and the
dashboard's advisor chat, and the surface that the v0.4.3.1 sub-agent
escape fix is supposed to protect. Pre-this-file it was stubbed in
every test that touched it — a future change to ``_build_config`` or
``_build_prompt`` that broke Bash sandboxing, env-scrubbing,
conversation truncation, or sub-agent denial fails no test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from urika.agents.runner import AgentResult


class _Recorder:
    """Records calls to ``runner.run`` and returns a scripted result."""

    def __init__(self, result: AgentResult):
        self._result = result
        self.calls: list[dict] = []

    async def run(self, config, prompt, *, on_message=None):  # noqa: ANN001
        self.calls.append(
            {"config": config, "prompt": prompt, "on_message": on_message}
        )
        return self._result


def _ok(text: str = "Sure, here's what I can tell you.") -> AgentResult:
    return AgentResult(
        success=True,
        messages=[],
        text_output=text,
        session_id="s",
        num_turns=1,
        duration_ms=1,
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.001,
        model="claude-test",
    )


def _fail(error: str, category: str = "unknown", partial: str = "") -> AgentResult:
    return AgentResult(
        success=False,
        messages=[],
        text_output=partial,
        session_id="s",
        num_turns=0,
        duration_ms=1,
        tokens_in=0,
        tokens_out=0,
        error=error,
        error_category=category,
        model="claude-test",
    )


def _make_chat(tmp_path: Path, monkeypatch, runner: _Recorder, *, with_project=True):
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace
    from urika.orchestrator.chat import OrchestratorChat

    if with_project:
        proj = tmp_path / "p"
        create_project_workspace(
            proj, ProjectConfig(name="p", question="Q?", mode="exploratory")
        )
    else:
        proj = None

    chat = OrchestratorChat(project_dir=proj)
    # The chat lazily fetches a runner the first call; pre-set ours.
    chat._runner = runner
    return chat, proj


# ── lifecycle ──────────────────────────────────────────────────


def test_set_project_resets_messages(tmp_path: Path, monkeypatch) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    chat.messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "older"},
    ]
    other = tmp_path / "other"
    other.mkdir()
    chat.set_project(other)
    assert chat.project_dir == other
    assert chat.messages == []


def test_get_messages_returns_copy(tmp_path: Path, monkeypatch) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    chat.messages = [{"role": "user", "content": "x"}]
    got = chat.get_messages()
    got.append({"role": "user", "content": "mutation"})
    assert len(chat.messages) == 1  # caller's mutation didn't reach internal state


def test_set_messages_replaces_history(tmp_path: Path, monkeypatch) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    chat.messages = [{"role": "user", "content": "old"}]
    chat.set_messages([{"role": "user", "content": "new"}])
    assert chat.messages == [{"role": "user", "content": "new"}]


def test_clear_empties_messages(tmp_path: Path, monkeypatch) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    chat.messages = [{"role": "user", "content": "x"}]
    chat.clear()
    assert chat.messages == []


# ── chat: happy path ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_returns_response_and_appends_history(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _Recorder(_ok("Glad to help."))
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)
    out = await chat.chat("hello")
    assert out["success"] is True
    assert out["response"] == "Glad to help."
    assert out["tokens_in"] == 10 and out["tokens_out"] == 20
    assert out["cost_usd"] == pytest.approx(0.001)
    assert not out["error_category"]  # success → no category (empty string or None)
    # History updated.
    assert chat.messages[-2] == {"role": "user", "content": "hello"}
    assert chat.messages[-1]["role"] == "assistant"
    assert "Glad to help." in chat.messages[-1]["content"]


@pytest.mark.asyncio
async def test_chat_invokes_runner_with_built_config_and_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _Recorder(_ok())
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)
    await chat.chat("hello")
    assert len(runner.calls) == 1
    cfg = runner.calls[0]["config"]
    prompt = runner.calls[0]["prompt"]
    assert cfg.name == "orchestrator"
    assert "hello" in prompt


# ── chat: failure paths ────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_failure_surfaces_error_and_category(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _Recorder(_fail("rate limited", category="rate_limit"))
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)
    out = await chat.chat("hello")
    assert out["success"] is False
    assert out["error_category"] == "rate_limit"
    # Response carries category prefix + raw error.
    assert "[rate_limit]" in out["response"]
    assert "rate limited" in out["response"]


@pytest.mark.asyncio
async def test_chat_failure_includes_partial_output(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _Recorder(
        _fail("session lost", category="auth", partial="I was about to say…")
    )
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)
    out = await chat.chat("hello")
    assert "partial output" in out["response"]
    assert "I was about to say" in out["response"]
    # History records the failure but doesn't lose the user message.
    assert chat.messages[-2]["role"] == "user"
    assert "Error" in chat.messages[-1]["content"]


# ── sub-agent escape (v0.4.3.1) ────────────────────────────────


def test_build_config_does_not_allow_sandbox_escape_tools(
    tmp_path: Path, monkeypatch
) -> None:
    """The orchestrator config must not list Task/Agent/ToolSearch in
    allowed_tools — the v0.4.3.1 sub-agent escape fix relies on these
    being absent (and the adapter additionally appends them to
    disallowed_tools as belt-and-braces)."""
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    cfg = chat._build_config()
    forbidden = {"Task", "Agent", "ToolSearch"}
    assert forbidden.isdisjoint(set(cfg.allowed_tools)), (
        f"orchestrator must not allow sandbox-escaping tools: {cfg.allowed_tools!r}"
    )


def test_build_config_with_no_project_has_no_bash(tmp_path: Path, monkeypatch) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()), with_project=False)
    cfg = chat._build_config()
    # Pre-project: chat-only, no Bash, no shell access at all.
    assert "Bash" not in cfg.allowed_tools
    assert cfg.security.allowed_bash_prefixes == []
    assert cfg.security.writable_dirs == []


def test_build_config_with_project_allows_urika_bash_only(
    tmp_path: Path, monkeypatch
) -> None:
    chat, proj = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    cfg = chat._build_config()
    assert "Bash" in cfg.allowed_tools
    # The only allowed shell head-token is ``urika``.
    assert cfg.security.allowed_bash_prefixes == ["urika"]
    # writable_dirs stays empty even with a project — the orchestrator
    # reads state but never writes via tools.
    assert cfg.security.writable_dirs == []
    # Project dir is readable (so state files can be Read).
    assert proj in cfg.security.readable_dirs
    # Blocked-bash patterns prevent raw-data exfiltration via cat/head.
    blocked = " ".join(cfg.security.blocked_bash_patterns)
    assert "data" in blocked


# ── env scrubbing at the chat boundary (v0.3.2) ────────────────


def test_build_config_scrubs_oauth_and_session_markers(
    tmp_path: Path, monkeypatch
) -> None:
    """Pre-v0.3.2 the scrub here was inlined and missed
    CLAUDE_CODE_EXECPATH / CLAUDE_CODE_OAUTH_TOKEN. Now the single
    source of truth is ``compliance.scrub_oauth_env``."""
    # Set the markers in process env; build_agent_env_for_endpoint
    # composes the agent env from os.environ.
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/should/be/gone")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret-token")
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "1234")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-code")
    monkeypatch.setenv("CLAUDECODE", "1")
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    cfg = chat._build_config()
    assert cfg.env is not None
    # scrub_oauth_env neutralises the markers by setting them to "" (the
    # SDK transport reads env via os.environ.get with default "" — it
    # treats empty-string as unset). Either fully removed or "" — both
    # are acceptable; the original values must be gone.
    for marker, original in (
        ("CLAUDE_CODE_EXECPATH", "/should/be/gone"),
        ("CLAUDE_CODE_OAUTH_TOKEN", "secret-token"),
        ("CLAUDE_CODE_SSE_PORT", "1234"),
        ("CLAUDE_CODE_ENTRYPOINT", "claude-code"),
        ("CLAUDECODE", "1"),
    ):
        assert cfg.env.get(marker, "") != original, (
            f"scrub_oauth_env left {marker!r}={original!r} in the agent env"
        )


# ── history truncation ─────────────────────────────────────────


def test_build_prompt_keeps_last_40_messages(tmp_path: Path, monkeypatch) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    # Seed 60 historic messages, alternating roles.
    chat.messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m-{i}"}
        for i in range(60)
    ]
    prompt = chat._build_prompt("now")
    # Earliest messages must be dropped (window is last 40).
    assert "m-0" not in prompt and "m-19" not in prompt
    # Window boundary present (the 20th-from-end message).
    assert "m-20" in prompt
    assert "m-59" in prompt
    # The new user message is the tail.
    assert prompt.rstrip().endswith("User: now")


def test_build_prompt_truncates_long_assistant_responses(
    tmp_path: Path, monkeypatch
) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    long_text = "x" * 800
    chat.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": long_text},
    ]
    prompt = chat._build_prompt("again")
    # 500-char limit + ellipsis marker.
    assert "x" * 500 in prompt
    assert "x" * 600 not in prompt
    assert "..." in prompt


def test_build_prompt_empty_history_includes_only_user(
    tmp_path: Path, monkeypatch
) -> None:
    chat, _ = _make_chat(tmp_path, monkeypatch, _Recorder(_ok()))
    prompt = chat._build_prompt("hello")
    assert "Recent Conversation" not in prompt
    assert prompt.endswith("User: hello")


# ── streaming / callbacks ──────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_passes_on_message_callback_to_runner(
    tmp_path: Path, monkeypatch
) -> None:
    runner = _Recorder(_ok())
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)
    await chat.chat("hello", on_output=lambda kind, text: None)
    assert runner.calls[0]["on_message"] is not None


@pytest.mark.asyncio
async def test_chat_notify_callback_invoked(tmp_path: Path, monkeypatch) -> None:
    runner = _Recorder(_ok())
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)
    events: list[tuple[str, dict]] = []
    await chat.chat("hello", notify=lambda e, d: events.append((e, d)))
    # At least "thinking" at start and "done" at end.
    kinds = [e for e, _ in events]
    assert "orchestrator.thinking" in kinds
    assert "orchestrator.done" in kinds


@pytest.mark.asyncio
async def test_chat_notify_exception_does_not_crash(
    tmp_path: Path, monkeypatch
) -> None:
    """A buggy notify callback must not propagate — pre-v0.3.2 a
    notify exception killed the run."""
    runner = _Recorder(_ok())
    chat, _ = _make_chat(tmp_path, monkeypatch, runner)

    def _bad_notify(e, d):  # noqa: ANN001
        raise RuntimeError("notify boom")

    out = await chat.chat("hello", notify=_bad_notify)
    assert out["success"] is True  # chat completed despite notify failure


# ── module-level singleton ─────────────────────────────────────


def test_get_orchestrator_returns_singleton() -> None:
    from urika.orchestrator import chat as chat_mod

    chat_mod._orchestrator = None  # reset
    a = chat_mod.get_orchestrator()
    b = chat_mod.get_orchestrator()
    assert a is b
    assert isinstance(a, chat_mod.OrchestratorChat)
