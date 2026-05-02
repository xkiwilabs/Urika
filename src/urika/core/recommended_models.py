"""Recommended per-agent model assignments.

Single source of truth for the **reasoning vs execution split** —
the cost-saving default that picks Opus (or the user's chosen
"best" model) for the four agents whose decision quality directly
shapes the experiment, and Sonnet 4.5 for the eight agents whose
work is execute-this-plan / format-these-numbers / apply-rules-to-
metrics. Sonnet performs indistinguishably from Opus on those
roles and saves roughly 5x per call.

Used by:
    - ``urika config`` interactive wizard (writes the split when the
      user picks Opus).
    - ``urika config --reset-models`` (re-applies the split to an
      existing project's or global's per-agent overrides — for users
      upgrading from a pre-v0.4.0 settings file or who manually
      drifted their per-agent map).
    - The dashboard's Models-tab "Reset to recommended defaults"
      button (same helper, server side).

Picking Sonnet or Haiku as the default skips the split entirely
(everything is already at the cheaper tier).
"""

from __future__ import annotations

# Agents whose decision quality directly shapes the experiment's
# trajectory — keep these on the user's selected "best" model.
REASONING_AGENTS: tuple[str, ...] = (
    "planning_agent",
    "advisor_agent",
    "finalizer",
    "project_builder",
)

# Agents whose work is "execute this plan" / "format these numbers" /
# "apply rule to metric". Sonnet 4.5 is indistinguishable from Opus
# on these, so we auto-pin to the cheaper tier when the user picks
# Opus as the mode default.
EXECUTION_AGENTS: tuple[str, ...] = (
    "task_agent",
    "evaluator",
    "report_agent",
    "presentation_agent",
    "tool_builder",
    "literature_agent",
    "data_agent",
    "project_summarizer",
)

# Cheaper-tier model used for execution agents when the user picks
# Opus. Single source of truth so the CLI wizard, the
# ``--reset-models`` flag, the dashboard's Models tab, and any
# future tooling agree.
EXECUTION_AGENT_DEFAULT_MODEL = "claude-sonnet-4-5"


def split_applies(default_model: str) -> bool:
    """True iff *default_model* is an Opus tier — split saves money.

    Sonnet / Haiku defaults skip the split (everything's already at
    the cheaper tier and per-agent overrides would just add noise).
    """
    return (default_model or "").lower().startswith("claude-opus")


def build_split_overrides(
    default_model: str,
    cloud_endpoint: str = "open",
    *,
    private_overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    """Return a per-agent override dict implementing the split.

    Keys are agent names; values are ``{"model": <str>, "endpoint":
    <str>}`` rows ready to write into ``[runtime.models.<agent>]``
    (project) or ``[runtime.modes.<mode>.models.<agent>]`` (global).

    Empty when *default_model* is not an Opus tier.

    *private_overrides* — for hybrid mode the caller passes
    ``{"data_agent": {"model": "qwen3:14b", "endpoint": "private"},
    "tool_builder": {"model": "qwen3:14b", "endpoint": "private"}}``
    so those two agents get pinned to the private endpoint instead
    of the cloud-Sonnet placeholder. Other privacy modes pass
    ``None``.
    """
    if not split_applies(default_model):
        return {}

    overrides: dict[str, dict[str, str]] = {}
    for agent in REASONING_AGENTS:
        overrides[agent] = {"model": default_model, "endpoint": cloud_endpoint}
    for agent in EXECUTION_AGENTS:
        overrides[agent] = {
            "model": EXECUTION_AGENT_DEFAULT_MODEL,
            "endpoint": cloud_endpoint,
        }

    if private_overrides:
        for agent, row in private_overrides.items():
            overrides[agent] = dict(row)

    return overrides


def reset_project_models(settings: dict, *, default_model: str | None = None) -> dict:
    """In-place rewrite of *settings* (project ``urika.toml``)
    per-agent model overrides to the recommended split.

    Reads the current ``[runtime].model`` (or *default_model* if
    explicitly provided) and rebuilds ``[runtime.models]`` from
    scratch — any existing custom overrides are dropped. Returns
    the same *settings* dict for chaining.

    For hybrid-mode projects, the data_agent + tool_builder
    private-endpoint pin is preserved if present in the old
    ``[runtime.models]`` block.
    """
    runtime = settings.setdefault("runtime", {})
    if default_model is None:
        default_model = runtime.get("model", "")

    # Carry forward private endpoint pins for hybrid mode so they
    # aren't blown away by the rebuild.
    privacy_mode = settings.get("privacy", {}).get("mode", "")
    private_overrides: dict[str, dict[str, str]] | None = None
    if privacy_mode == "hybrid":
        old_models = runtime.get("models", {}) or {}
        private_overrides = {}
        for agent in ("data_agent", "tool_builder"):
            existing = old_models.get(agent)
            if isinstance(existing, dict) and existing.get("endpoint") == "private":
                private_overrides[agent] = {
                    "model": existing.get("model", ""),
                    "endpoint": "private",
                }
        if not private_overrides:
            private_overrides = None

    overrides = build_split_overrides(
        default_model, cloud_endpoint="open",
        private_overrides=private_overrides,
    )
    if overrides:
        runtime["models"] = overrides
    else:
        runtime.pop("models", None)
    return settings


def reset_global_models(settings: dict) -> dict:
    """In-place rewrite of *settings* (``~/.urika/settings.toml``)
    per-agent overrides under ``[runtime.modes.<mode>.models]`` for
    each configured mode (open / private / hybrid). Returns the
    same *settings* dict for chaining.

    Hybrid mode preserves data_agent + tool_builder private pins
    the same way :func:`reset_project_models` does.
    """
    runtime = settings.setdefault("runtime", {})
    modes = runtime.setdefault("modes", {})
    for mode_name in ("open", "private", "hybrid"):
        mode_cfg = modes.get(mode_name)
        if not isinstance(mode_cfg, dict):
            continue
        default_model = mode_cfg.get("model", "")

        private_overrides: dict[str, dict[str, str]] | None = None
        if mode_name == "hybrid":
            old_models = mode_cfg.get("models", {}) or {}
            private_overrides = {}
            for agent in ("data_agent", "tool_builder"):
                existing = old_models.get(agent)
                if isinstance(existing, dict) and existing.get("endpoint") == "private":
                    private_overrides[agent] = {
                        "model": existing.get("model", ""),
                        "endpoint": "private",
                    }
            if not private_overrides:
                private_overrides = None

        overrides = build_split_overrides(
            default_model, cloud_endpoint="open",
            private_overrides=private_overrides,
        )
        if overrides:
            mode_cfg["models"] = overrides
        else:
            mode_cfg.pop("models", None)
    return settings
