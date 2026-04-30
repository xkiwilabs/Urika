"""Tests for AgentRunner ABC and AgentResult."""

from __future__ import annotations

import pytest

from urika.agents.runner import AgentResult, AgentRunner


class TestAgentResult:
    def test_successful_result(self) -> None:
        result = AgentResult(
            success=True,
            messages=[{"type": "text", "content": "Hello"}],
            text_output="Hello",
            session_id="session-001",
            num_turns=3,
            duration_ms=1500,
        )
        assert result.success is True
        assert result.cost_usd is None
        assert result.error is None

    def test_failed_result(self) -> None:
        result = AgentResult(
            success=False,
            messages=[],
            text_output="",
            session_id="session-002",
            num_turns=0,
            duration_ms=100,
            error="Connection failed",
        )
        assert result.success is False
        assert result.error == "Connection failed"


class TestAgentRunnerABC:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            AgentRunner()  # type: ignore[abstract]


# ── v0.4: entry-point discovery ────────────────────────────────────


class TestRunnerEntryPoints:
    """v0.4 thin abstraction: external adapters register via the
    ``urika.runners`` entry-point group. The factory loads them
    lazily on first ``get_runner`` call.
    """

    def test_get_runner_claude_returns_real_runner(self):
        """Built-in 'claude' backend always available."""
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner
        from urika.agents.runner import get_runner

        runner = get_runner("claude")
        assert isinstance(runner, ClaudeSDKRunner)

    def test_get_runner_unknown_backend_lists_available(self):
        from urika.agents.runner import get_runner

        with pytest.raises(ValueError) as ctx:
            get_runner("nope")
        msg = str(ctx.value)
        assert "claude" in msg
        assert "contributing-an-adapter" in msg

    def test_list_backends_includes_claude(self):
        from urika.agents.runner import list_backends

        assert "claude" in list_backends()

    def test_runner_required_env_default_is_empty(self):
        from urika.agents.runner import AgentRunner

        assert AgentRunner.required_env() == ()

    def test_runner_supported_tools_default_is_empty(self):
        from urika.agents.runner import AgentRunner

        assert AgentRunner.supported_tools() == frozenset()

    def test_discover_runners_loads_third_party(self, monkeypatch):
        """A registered third-party adapter shows up in list_backends
        and resolves via get_runner."""
        from urika.agents import runner as runner_mod
        from urika.agents.runner import AgentRunner, AgentResult

        class FakeRunner(AgentRunner):
            async def run(self, config, prompt, *, on_message=None):
                return AgentResult(
                    success=True,
                    messages=[],
                    text_output="fake",
                    session_id="fake",
                )

        # Bypass the cache + the entry-points walk by injecting
        # directly into the module-level cache.
        monkeypatch.setattr(runner_mod, "_RUNNER_CACHE", {"fake": FakeRunner})
        assert "fake" in runner_mod.list_backends()
        r = runner_mod.get_runner("fake")
        assert isinstance(r, FakeRunner)

    def test_discover_runners_skips_non_subclass(self, monkeypatch, caplog):
        """Entry-point classes that aren't AgentRunner subclasses are
        logged + skipped rather than crashing the discovery."""
        from urika.agents import runner as runner_mod

        class NotARunner:
            pass

        # Force a fresh discovery with a controlled entry-points list.
        class _FakeEP:
            def __init__(self, name, cls):
                self.name = name
                self._cls = cls

            def load(self):
                return self._cls

        def fake_entry_points(group: str):
            assert group == "urika.runners"
            return [_FakeEP("bogus", NotARunner)]

        from importlib import metadata as md

        monkeypatch.setattr(runner_mod, "_RUNNER_CACHE", None)
        monkeypatch.setattr(md, "entry_points", fake_entry_points)
        # Reset and call discovery via the public factory path.
        with caplog.at_level("WARNING", logger="urika.agents.runner"):
            with pytest.raises(ValueError):
                runner_mod.get_runner("bogus")
        assert any("not an AgentRunner subclass" in r.message for r in caplog.records)
