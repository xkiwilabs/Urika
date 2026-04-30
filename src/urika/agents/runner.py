"""Agent runner interface and result types — runtime-agnostic.

Multi-provider thin abstraction (v0.4 Track 3): the ``AgentRunner``
ABC, ``AgentResult`` dataclass, and ``get_runner`` factory are
provider-agnostic. Today only ``ClaudeSDKRunner`` ships, but
contributors can register additional adapters via the
``urika.runners`` entry-point group:

    [project.entry-points."urika.runners"]
    openai = "my_pkg.openai_runner:OpenAIRunner"

Then ``get_runner("openai")`` will load and instantiate it.

The end-to-end second adapter (most-mature candidate: OpenAI Agents
SDK) is deferred to v0.5 — the v0.4 thin abstraction just ensures
the seam is real so external work can land without modifying core.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from urika.agents.config import AgentConfig

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """What an agent run produced."""

    success: bool
    messages: list[dict[str, Any]]
    text_output: str
    session_id: str
    num_turns: int = -1
    duration_ms: int = -1
    cost_usd: float | None = None
    error: str | None = None
    error_category: str = ""  # "rate_limit"/"auth"/"billing"/"transient"/"config" or ""
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class AgentRunner(ABC):
    """Run an agent and get results — implemented by adapters.

    Subclass and register via the ``urika.runners`` entry-point group
    in ``pyproject.toml`` to add a new provider. See
    ``docs/contributing-an-adapter.md``.
    """

    @abstractmethod
    async def run(
        self, config: AgentConfig, prompt: str, *, on_message: Callable[..., Any] | None = None
    ) -> AgentResult:
        """Execute an agent with the given config and prompt.

        on_message: optional callback called with each SDK message as it arrives.
        """
        ...

    @classmethod
    def required_env(cls) -> tuple[str, ...]:
        """Env-var names this adapter needs in os.environ to run.

        Default: empty tuple (adapter brings its own auth via
        ``AgentConfig.env`` overlay). Adapters that need a key like
        ``OPENAI_API_KEY`` declare it here so callers can probe
        before spawning.
        """
        return ()

    @classmethod
    def supported_tools(cls) -> frozenset[str]:
        """Canonical tool names this adapter implements.

        Empty frozenset means "trust the agent role's
        ``allowed_tools`` list". Adapters can override to advertise
        a subset (e.g. an OpenAI adapter that doesn't expose Bash
        would return ``frozenset({"Read", "Write", "WebFetch"})``).
        """
        return frozenset()


# Module-level cache for the discovered adapter map. Built lazily on
# first ``get_runner`` call so we don't pay the entry-points scan
# cost at import time.
_RUNNER_CACHE: dict[str, type[AgentRunner]] | None = None


def _discover_runners() -> dict[str, type[AgentRunner]]:
    """Walk the ``urika.runners`` entry-point group.

    Returns a name → class map. Loading is best-effort: any adapter
    whose module import fails is logged and skipped, so a broken
    third-party package can't break the whole runtime. The built-in
    ``claude`` adapter is always registered — entry points add to
    the map but can't override the built-in name.
    """
    discovered: dict[str, type[AgentRunner]] = {}
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="urika.runners"):
            try:
                cls = ep.load()
            except Exception as exc:
                logger.warning(
                    "Skipping runner entry-point %r: %s: %s",
                    ep.name,
                    type(exc).__name__,
                    exc,
                )
                continue
            if not (isinstance(cls, type) and issubclass(cls, AgentRunner)):
                logger.warning(
                    "Runner entry-point %r is not an AgentRunner subclass; skipping",
                    ep.name,
                )
                continue
            if ep.name == "claude":
                # Built-in name reserved.
                logger.warning(
                    "Runner entry-point %r conflicts with built-in 'claude'; ignoring",
                    ep.name,
                )
                continue
            discovered[ep.name] = cls
    except Exception as exc:
        # Don't fail startup if entry-points discovery itself breaks.
        logger.warning(
            "Runner entry-points discovery failed: %s: %s",
            type(exc).__name__,
            exc,
        )
    return discovered


def list_backends() -> list[str]:
    """Return every backend name ``get_runner`` can resolve."""
    discovered = _RUNNER_CACHE if _RUNNER_CACHE is not None else _discover_runners()
    return sorted({"claude", *discovered.keys()})


def get_runner(backend: str = "claude", **kwargs: object) -> AgentRunner:
    """Get an AgentRunner for the specified backend.

    The built-in ``"claude"`` backend is always available. Additional
    backends are discovered from the ``urika.runners`` entry-point
    group (see ``docs/contributing-an-adapter.md``). Pre-v0.4 the
    factory raised ``ValueError`` for any non-claude backend with
    no extension path — v0.4 opens it up.
    """
    global _RUNNER_CACHE
    if backend == "claude":
        from urika.agents.adapters.claude_sdk import ClaudeSDKRunner

        return ClaudeSDKRunner()
    if _RUNNER_CACHE is None:
        _RUNNER_CACHE = _discover_runners()
    cls = _RUNNER_CACHE.get(backend)
    if cls is not None:
        return cls()
    available = ", ".join(list_backends())
    raise ValueError(
        f"Backend {backend!r} is not registered. "
        f"Available: {available}. "
        f"To add an adapter, register it under the ``urika.runners`` "
        f"entry-point group — see docs/contributing-an-adapter.md."
    )
