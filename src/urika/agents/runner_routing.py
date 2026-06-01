"""Project- and agent-aware AgentRunner resolution.

v0.7.0 Task 1.5 wiring: this module is the shared helper used by every
support-agent call site (``urika advisor`` / ``evaluate`` / ``plan`` /
``finalize`` / ``report`` / ``present`` / ``build-tool`` / ``summarize``
/ ``memory curate`` / the conversational orchestrator / the RPC server
/ the REPL & TUI / the dashboard's agent-launching endpoints / the
project builder) to obtain the right :class:`~urika.agents.runner.AgentRunner`
for a given project + optional per-agent override.

Two entry points:

* :func:`runner_for_project` — resolve the project-level default model
  (``[runtime].model`` in ``urika.toml``, with global per-mode
  fallback). This mirrors the existing ``cli/run._resolve_runner``
  semantics and is the right helper for orchestrator-level entry
  points (the experiment loop, finalize sequence, presentation
  generator) which spin up multiple agents under a single runner.

* :func:`runner_for_agent` — resolve the per-agent model
  (``[runtime.models.<agent>]`` in ``urika.toml``, falling back to the
  project default). This is the right helper for standalone agent
  invocations — the bulk of the rewired call sites.

Both helpers degrade gracefully:

1. If ``urika.toml`` can't be loaded (no project, parse error, etc.)
   they return ``get_runner()`` — the legacy Claude default.
2. If the resolved model has no registered adapter prefix
   (``UnknownModelError``), they return ``get_runner()`` — preserves
   the pre-v0.7.0 behaviour for users with stray model strings.
3. If the adapter module itself can't be imported
   (``ModuleNotFoundError`` from a missing optional extra like
   ``urika[openai]`` or ``urika[google]``), they raise
   :class:`AdapterNotInstalledError` with a clear "pip install
   urika[<provider>]" hint. This is louder than fallback-to-Claude
   because a user who explicitly set ``gpt-5`` in their config is in
   trouble if we silently route to Claude — the bill goes to the
   wrong project and the agent uses the wrong model.

The OpenAI + Google adapter modules currently import their respective
SDKs lazily inside ``run()`` (not at module level), so today the
``ModuleNotFoundError`` branch only fires if a third-party adapter
registered via the ``urika.runners`` entry-point group imports a
missing extra at module-level. Catching it here is defensive: the
moment a future adapter or a contributor's package does have a
module-level optional import, the routing layer surfaces the right
message instead of leaking a raw ``ModuleNotFoundError``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from urika.agents.runner import AgentRunner

logger = logging.getLogger(__name__)


def _default_runner() -> "AgentRunner":
    """Return the legacy :func:`urika.agents.runner.get_runner` runner.

    Imported lazily inside the helper so that ``unittest.mock.patch``
    on ``urika.agents.runner.get_runner`` (used widely across the
    existing test suite to stub out the SDK) is honoured. A
    module-level ``from urika.agents.runner import get_runner`` would
    bind the name into this module's namespace and bypass the patch.
    """
    from urika.agents.runner import get_runner

    return get_runner()


class AdapterNotInstalledError(RuntimeError):
    """Raised when a model routes to an adapter whose extra isn't installed.

    Carries an actionable install hint in the message so callers can
    surface it verbatim to the user (CLI / dashboard / TUI).
    """


def _provider_extra_for_model(model: str) -> str:
    """Best-guess of the install extra a model needs.

    Used only to enrich the :class:`AdapterNotInstalledError` message —
    routing itself is the registry's job. Falls back to the literal
    model string when we don't recognise the prefix (which already
    can't happen here since ``UnknownModelError`` was filtered
    upstream — defensive code path only).
    """
    if model.startswith(("gpt-", "o3", "o4", "o5")):
        return "openai"
    if model.startswith("gemini-"):
        return "google"
    if model.startswith("claude-"):
        # claude is the default install — no extra needed. We'd only
        # get here if claude_sdk itself couldn't be imported, which
        # would be a broken install, not a missing extra.
        return "claude"
    return model


def _resolve(model: str) -> AgentRunner:
    """Route ``model`` to its adapter, with friendly errors.

    Internal helper. Public entry points (:func:`runner_for_project`
    and :func:`runner_for_agent`) call this after resolving the model
    string from project + per-agent config.

    * Empty model → legacy default (``get_runner()``).
    * Unknown prefix → legacy default (preserves pre-v0.7.0 behaviour
      for users with stray strings).
    * Known prefix but adapter module can't import → raise
      :class:`AdapterNotInstalledError` with an install hint.
    """
    from urika.agents.runner_registry import UnknownModelError, runner_for

    model = (model or "").strip()
    if not model:
        return _default_runner()
    try:
        return runner_for(model)
    except UnknownModelError:
        # Unknown prefix — fall back so pre-v0.7.0 setups are never
        # broken by a stray model string. The registry accepts
        # ``claude-*`` already; this only triggers for an explicit
        # non-claude string with no registered prefix.
        logger.warning(
            "No adapter registered for model %r — falling back to default runner",
            model,
        )
        return _default_runner()
    except ModuleNotFoundError as exc:
        # Adapter is registered but its module-level imports failed —
        # most likely a missing optional extra. Re-raise with an
        # actionable hint so the caller can surface it to the user
        # (CLI / dashboard / TUI all bubble RuntimeErrors with their
        # message text).
        extra = _provider_extra_for_model(model)
        raise AdapterNotInstalledError(
            f"Model {model!r} routes to an adapter whose dependencies "
            f"aren't installed ({exc.name or exc}). "
            f"Run: pip install urika[{extra}]"
        ) from exc


def runner_for_project(project_path: Path | None) -> AgentRunner:
    """Resolve the AgentRunner for a project's default model.

    Reads ``[runtime].model`` from ``project_path/urika.toml`` (with
    global per-mode fallback handled by
    :func:`urika.agents.config.load_runtime_config`) and routes via
    :func:`urika.agents.runner_registry.runner_for`. Falls back to the
    legacy :func:`get_runner` when no model is configured.

    Use this for orchestrator-level entry points that drive multiple
    agents under a single runner (experiment loop, finalize sequence,
    presentation generator). For standalone single-agent invocations
    prefer :func:`runner_for_agent`, which honours
    ``[runtime.models.<agent>]`` overrides.

    ``project_path=None`` is accepted and returns the legacy default —
    convenience for bootstrap paths where no project context exists yet.
    """
    if project_path is None:
        return _default_runner()

    from urika.agents.config import load_runtime_config

    try:
        rc = load_runtime_config(Path(project_path))
    except Exception as exc:  # pragma: no cover — pass-through to default
        logger.warning(
            "Could not load runtime config from %s: %s — using default runner",
            project_path,
            exc,
        )
        return _default_runner()

    return _resolve(rc.model or "")


def runner_for_agent(agent_name: str, project_path: Path | None) -> AgentRunner:
    """Resolve the AgentRunner for a specific agent in a project.

    Reads ``[runtime.models.<agent_name>]`` from
    ``project_path/urika.toml`` (with global per-mode fallback) and
    falls back to ``[runtime].model`` when no per-agent override is
    set. Routes via :func:`urika.agents.runner_registry.runner_for`.

    This is the primary helper for standalone agent invocations —
    everywhere a CLI command, REPL slash command, RPC method, or
    dashboard endpoint runs a single agent (advisor / evaluator /
    planning_agent / report_agent / presentation_agent /
    project_summarizer / tool_builder / memory_curator /
    project_builder).

    ``project_path=None`` is accepted and returns the legacy default.
    """
    if project_path is None:
        return _default_runner()

    from urika.agents.config import get_agent_model, load_runtime_config

    try:
        rc = load_runtime_config(Path(project_path))
    except Exception as exc:  # pragma: no cover — pass-through to default
        logger.warning(
            "Could not load runtime config from %s: %s — using default runner",
            project_path,
            exc,
        )
        return _default_runner()

    model = get_agent_model(agent_name, rc) or ""
    return _resolve(model)
