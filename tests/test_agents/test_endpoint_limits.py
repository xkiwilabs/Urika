"""Per-endpoint context_window + max_output_tokens (v0.4.1).

Regression: pre-v0.4.1 the bundled ``claude`` CLI always requested 32K
output tokens by default, which alone fills a 32K-window vLLM endpoint
and yields HTTP 400 ``ContextWindowExceededError``. This was the
blocker for the v0.4 E2E private-mode smoke. The fix exposes
``context_window`` and ``max_output_tokens`` per endpoint and forwards
them to the CLI via ``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` /
``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` env vars.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from urika.agents.config import (
    EndpointConfig,
    build_agent_env_for_endpoint,
    resolve_endpoint_limits,
)


class TestResolveEndpointLimits:
    """Auto-default resolution for ``EndpointConfig`` (no I/O)."""

    def test_anthropic_url_gets_cloud_defaults(self) -> None:
        ep = EndpointConfig(base_url="https://api.anthropic.com")
        cw, mo = resolve_endpoint_limits(ep)
        assert cw == 200_000
        assert mo == 32_000

    def test_local_url_gets_conservative_defaults(self) -> None:
        ep = EndpointConfig(base_url="http://localhost:11434")
        cw, mo = resolve_endpoint_limits(ep)
        assert cw == 32_768
        assert mo == 8_000

    def test_vllm_remote_url_gets_local_defaults(self) -> None:
        """Anything that isn't anthropic.com falls into the local
        bucket — the conservative defaults are the safe choice for
        any endpoint we can't introspect."""
        ep = EndpointConfig(base_url="http://100.127.175.6:4200")
        cw, mo = resolve_endpoint_limits(ep)
        assert cw == 32_768
        assert mo == 8_000

    def test_explicit_declaration_overrides_default(self) -> None:
        ep = EndpointConfig(
            base_url="http://localhost:8000",
            context_window=128_000,
            max_output_tokens=16_000,
        )
        cw, mo = resolve_endpoint_limits(ep)
        assert cw == 128_000
        assert mo == 16_000

    def test_partial_declaration_resolves_other_field(self) -> None:
        """A user can declare just one of the two and the other auto-
        resolves — common when the user knows the window but is happy
        with the conservative output cap."""
        ep = EndpointConfig(
            base_url="http://localhost:8000",
            context_window=128_000,
            # max_output_tokens left at 0 → auto-default
        )
        cw, mo = resolve_endpoint_limits(ep)
        assert cw == 128_000
        assert mo == 8_000  # auto-default for non-anthropic URL


class TestBuildAgentEnvForEndpoint:
    """End-to-end: TOML → AgentConfig env should carry the
    CLAUDE_CODE_MAX_* env vars when a private endpoint is configured."""

    def _make_project(
        self, root: Path, mode: str, base_url: str, *,
        context_window: int = 0, max_output_tokens: int = 0,
    ) -> Path:
        proj = root / "alpha"
        proj.mkdir(parents=True)
        toml_lines = [
            '[project]',
            'name = "alpha"',
            'question = "?"',
            f'mode = "{mode}"',
            'description = ""',
            '',
            '[privacy]',
            f'mode = "{mode}"',
            '',
            '[privacy.endpoints.private]',
            f'base_url = "{base_url}"',
            'api_key_env = "TEST_KEY"',
        ]
        if context_window:
            toml_lines.append(f"context_window = {context_window}")
        if max_output_tokens:
            toml_lines.append(f"max_output_tokens = {max_output_tokens}")
        (proj / "urika.toml").write_text("\n".join(toml_lines) + "\n")
        return proj

    def test_private_local_endpoint_gets_capped_output(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Regression: v0.4 E2E private-mode smoke hit
        ContextWindowExceededError because the CLI requested 32K
        output against a 32K-window vLLM. The fix sets
        CLAUDE_CODE_MAX_OUTPUT_TOKENS=8000 (conservative auto-default)
        so the request fits."""
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.setenv("TEST_KEY", "x")
        proj = self._make_project(tmp_path, "private", "http://100.127.175.6:4200")

        env = build_agent_env_for_endpoint(proj, "task_agent")
        assert env is not None
        assert env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS") == "32768"
        assert env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") == "8000"
        # Sanity: the existing base_url + auth wiring is unaffected.
        assert env.get("ANTHROPIC_BASE_URL") == "http://100.127.175.6:4200"
        assert env.get("ANTHROPIC_AUTH_TOKEN") == "x"

    def test_explicit_declaration_propagates_to_env(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """User-declared values win over the auto-default. A user with
        a 128K-window vLLM should be able to opt in to bigger output."""
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.setenv("TEST_KEY", "x")
        proj = self._make_project(
            tmp_path, "private", "http://localhost:8000",
            context_window=128_000, max_output_tokens=16_000,
        )

        env = build_agent_env_for_endpoint(proj, "task_agent")
        assert env is not None
        assert env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS") == "128000"
        assert env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") == "16000"

    def test_open_mode_does_not_inject_caps(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Cloud (open mode) callers must see no behaviour change.
        The bundled CLI's own defaults remain authoritative for
        api.anthropic.com requests; we only inject when a non-open
        endpoint is configured. Otherwise any pre-v0.4.1 user with a
        well-tuned cloud workflow would suddenly see a different
        output budget on upgrade."""
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        proj = tmp_path / "alpha"
        proj.mkdir()
        (proj / "urika.toml").write_text(
            '[project]\nname = "alpha"\nquestion = "?"\n'
            'mode = "exploratory"\n[privacy]\nmode = "open"\n'
        )

        env = build_agent_env_for_endpoint(proj, "task_agent")
        # ``env is None`` is the sentinel for "use process env as-is";
        # either way the caps must NOT be set.
        if env is not None:
            assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in env
            assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in env

    def test_anthropic_named_endpoint_keeps_cloud_defaults(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A user who declares a named endpoint pointing at the
        Anthropic cloud (e.g. for a custom auth flow) gets the cloud
        defaults — not the conservative local ones — so input headroom
        stays at 200K."""
        monkeypatch.setenv("URIKA_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.setenv("TEST_KEY", "x")
        proj = self._make_project(
            tmp_path, "private", "https://api.anthropic.com"
        )

        env = build_agent_env_for_endpoint(proj, "task_agent")
        assert env is not None
        assert env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS") == "200000"
        assert env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") == "32000"
