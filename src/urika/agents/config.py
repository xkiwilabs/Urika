"""Agent configuration and security policy — runtime-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class MissingPrivateEndpointError(RuntimeError):
    """Raised when a privacy-sensitive agent run requires a configured
    private endpoint that is missing from the runtime config.

    The runtime used to silently fall back to the cloud endpoint and
    only emit a ``warnings.warn(...)``.  That made it possible to run
    a project in ``private`` (or ``hybrid``) mode while quietly
    sending data to the Anthropic API — the opposite of the
    user-facing privacy contract.

    Now ``build_agent_env_for_endpoint`` raises this error when the
    selected endpoint is missing, so the run aborts visibly and the
    user is forced to fix the configuration before any
    privacy-sensitive workload starts.
    """

    pass


@dataclass
class SecurityPolicy:
    """Filesystem and command boundaries for an agent.

    **Enforced at runtime as of v0.4** via the SDK's ``can_use_tool``
    permission callback. ``ClaudeSDKRunner._build_options`` wires
    each agent's policy into a ``can_use_tool`` coroutine that the
    SDK invokes before every tool dispatch
    (``urika.agents.permission.make_can_use_tool``). The methods here
    (``is_write_allowed``, ``is_bash_allowed``) are kept for unit
    tests + introspection but are NOT the enforcement code path —
    the SDK callback uses ``permission._decide`` directly so the
    policy is applied to the actual ``tool_input`` dict the SDK
    receives, including path canonicalisation that defeats ``..``
    and symlinks.

    Pre-v0.4 these fields were advisory only: a doc lie that the
    v0.3.2 audit explicitly flagged. The orchestrator chat's
    ``allowed_bash_prefixes=["urika ", "CLAUDECODE= urika "]`` was
    paper — ``urika ; rm -rf /`` matched the prefix.
    """

    writable_dirs: list[Path]
    readable_dirs: list[Path]
    allowed_bash_prefixes: list[str]
    blocked_bash_patterns: list[str]

    def is_write_allowed(self, path: Path) -> bool:
        """Check if a file path is within any writable directory.

        Used by tests + introspection. The runtime enforcement path
        is ``permission._path_decision`` which has identical logic
        but operates on the SDK's ``tool_input`` directly with full
        symlink resolution.
        """
        resolved = path.resolve()
        return any(
            resolved == d.resolve() or _is_relative_to(resolved, d.resolve())
            for d in self.writable_dirs
        )

    def is_bash_allowed(self, command: str) -> bool:
        """Check if a bash command is allowed by prefix rules and not blocked.

        Used by tests + introspection. The runtime enforcement path
        is ``permission._bash_decision`` which additionally
        shlex-parses + rejects shell metacharacters (so
        ``urika ; rm -rf /`` is denied even when ``urika`` is
        allow-listed).
        """
        cmd = command.strip()
        for pattern in self.blocked_bash_patterns:
            if pattern in cmd:
                return False
        if not self.allowed_bash_prefixes:
            return True
        return any(cmd.startswith(prefix) for prefix in self.allowed_bash_prefixes)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Check if path is relative to parent."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


@dataclass
class AgentConfig:
    """What an agent needs to run — runtime-agnostic."""

    name: str
    system_prompt: str
    allowed_tools: list[str]
    disallowed_tools: list[str]
    security: SecurityPolicy
    max_turns: int = 50
    model: str | None = None
    cwd: Path | None = None
    env: dict[str, str] | None = None  # environment vars for agent subprocess


@dataclass
class EndpointConfig:
    """A named API endpoint."""

    base_url: str = ""  # empty = default Anthropic API
    api_key_env: str = ""  # env var name containing the API key (e.g. "UNI_API_KEY")
    # v0.4.1: context-window declaration. Local endpoints (vLLM,
    # LiteLLM, OpenRouter, Ollama, LM Studio) typically have hard
    # 32K-128K windows; the bundled ``claude`` CLI requests 32K
    # output by default, which alone fills a 32K-window endpoint and
    # produces HTTP 400 ``ContextWindowExceededError``. Setting these
    # fields surfaces the limit to the CLI via
    # ``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` and
    # ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` so the request fits.
    # Both default to 0 = "use auto-default for this URL" (see
    # ``resolve_endpoint_limits``).
    context_window: int = 0
    max_output_tokens: int = 0


def resolve_endpoint_limits(endpoint: EndpointConfig) -> tuple[int, int]:
    """Return ``(context_window, max_output_tokens)`` with auto-defaults.

    When an endpoint declares either field, the declared value is
    used. When a field is 0 (the default), it falls back to a
    URL-based default:

    * api.anthropic.com → ``200000`` / ``32000`` (preserves the
      cloud experience pre-v0.4.1).
    * Anything else (private vLLM / LiteLLM / OpenRouter / Ollama /
      LM Studio / etc.) → ``32768`` / ``8000``. Conservative; leaves
      ~24K for input. Endpoints with bigger windows should declare
      explicitly.

    The two values are independent so a user can declare one and
    let the other auto-resolve.
    """
    is_anthropic = "anthropic.com" in (endpoint.base_url or "").lower()
    cw = endpoint.context_window or (200000 if is_anthropic else 32768)
    mo = endpoint.max_output_tokens or (32000 if is_anthropic else 8000)
    return cw, mo


@dataclass
class AgentModelConfig:
    """Per-agent model and endpoint assignment."""

    endpoint: str = "open"  # name from [privacy.endpoints]
    model: str = ""  # model name, empty = use default


@dataclass
class RuntimeConfig:
    """Project-level runtime configuration."""

    backend: str = "claude"
    model: str = ""
    model_overrides: dict[str, AgentModelConfig] = field(default_factory=dict)
    privacy_mode: str = "open"  # open | private | hybrid
    endpoints: dict[str, EndpointConfig] = field(default_factory=dict)


def _load_global_per_mode(mode: str) -> tuple[str, dict[str, AgentModelConfig]]:
    """Read ``[runtime.modes.<mode>]`` from ``~/.urika/settings.toml``.

    Returns ``(default_model, per_agent_overrides)`` extracted from
    ``[runtime.modes.<mode>].model`` and
    ``[runtime.modes.<mode>.models.<agent>]``.  Empty values are returned
    when the file is missing, unparseable, or has no block for ``mode``.
    """
    import tomllib

    from urika.core.settings import _settings_path

    path = _settings_path()
    if not path.exists():
        return "", {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return "", {}

    modes = data.get("runtime", {}).get("modes", {})
    if not isinstance(modes, dict):
        return "", {}
    cfg = modes.get(mode, {})
    if not isinstance(cfg, dict):
        return "", {}

    default_model = cfg.get("model", "") or ""
    per_agent: dict[str, AgentModelConfig] = {}
    for agent_name, agent_cfg in (cfg.get("models", {}) or {}).items():
        if isinstance(agent_cfg, dict):
            per_agent[agent_name] = AgentModelConfig(
                endpoint=agent_cfg.get("endpoint", "open"),
                model=agent_cfg.get("model", ""),
            )
        elif isinstance(agent_cfg, str):
            per_agent[agent_name] = AgentModelConfig(model=agent_cfg)
    return default_model, per_agent


def load_runtime_config(project_dir: Path) -> RuntimeConfig:
    """Load runtime config from urika.toml. Returns defaults if not configured.

    Project-level overrides always win.  When the project's ``urika.toml``
    has no entry for a given agent (or no top-level ``[runtime].model``),
    the loader falls back to ``[runtime.modes.<project_mode>]`` in
    ``~/.urika/settings.toml``.  This is the live-inheritance bit of the
    global-defaults model: projects pick a mode and get per-agent
    defaults from globals without copying them at creation time.
    """
    import tomllib

    toml_path = project_dir / "urika.toml"
    if not toml_path.exists():
        return RuntimeConfig()
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        runtime = data.get("runtime", {})
        privacy = data.get("privacy", {})

        # Parse per-agent model overrides from [runtime.models.<agent_name>]
        raw_models = runtime.get("models", {})
        model_overrides: dict[str, AgentModelConfig] = {}
        for agent_name, agent_cfg in raw_models.items():
            if isinstance(agent_cfg, dict):
                model_overrides[agent_name] = AgentModelConfig(
                    endpoint=agent_cfg.get("endpoint", "open"),
                    model=agent_cfg.get("model", ""),
                )
            elif isinstance(agent_cfg, str):
                # Backward compat: plain string is treated as model name
                model_overrides[agent_name] = AgentModelConfig(model=agent_cfg)

        # Parse endpoint definitions from [privacy.endpoints.<name>]
        raw_endpoints = privacy.get("endpoints", {})
        endpoints: dict[str, EndpointConfig] = {}
        for ep_name, ep_cfg in raw_endpoints.items():
            if isinstance(ep_cfg, dict):
                endpoints[ep_name] = EndpointConfig(
                    base_url=ep_cfg.get("base_url", ""),
                    api_key_env=ep_cfg.get("api_key_env", ""),
                    context_window=int(ep_cfg.get("context_window", 0) or 0),
                    max_output_tokens=int(
                        ep_cfg.get("max_output_tokens", 0) or 0
                    ),
                )

        # ── Live-inherit endpoint definitions from globals ────────────
        # Project-level [privacy.endpoints.<name>] always wins on
        # collision; globals fill in any name the project hasn't defined.
        # Mirrors the per-mode model live-inheritance pattern below — the
        # dashboard's POST /api/projects writes only [privacy].mode (not
        # endpoint duplicates), so without this the loader would crash
        # on the next agent invocation with MissingPrivateEndpointError.
        from urika.core.settings import get_named_endpoints

        for ep in get_named_endpoints():
            ep_name = ep.get("name", "")
            if not ep_name or ep_name in endpoints:
                continue
            endpoints[ep_name] = EndpointConfig(
                base_url=ep.get("base_url", ""),
                api_key_env=ep.get("api_key_env", ""),
                context_window=int(ep.get("context_window", 0) or 0),
                max_output_tokens=int(ep.get("max_output_tokens", 0) or 0),
            )

        # ── Live-inherit from global per-mode defaults ────────────────
        # Project-level values always win; globals fill in the gaps for
        # any agent (or the top-level model) that the project hasn't
        # overridden.
        project_mode = privacy.get("mode", "open")
        global_default_model, global_per_agent = _load_global_per_mode(project_mode)
        for agent_name, gcfg in global_per_agent.items():
            if agent_name not in model_overrides:
                model_overrides[agent_name] = gcfg

        final_model = runtime.get("model", "") or global_default_model

        return RuntimeConfig(
            backend=runtime.get("backend", "claude"),
            model=final_model,
            model_overrides=model_overrides,
            privacy_mode=project_mode,
            endpoints=endpoints,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to load runtime config from %s: %s — using defaults", toml_path, exc
        )
        return RuntimeConfig()



def build_agent_env_for_endpoint(
    project_dir: Path,
    agent_name: str,
    runtime_config: RuntimeConfig | None = None,
) -> dict[str, str] | None:
    """Build environment dict for an agent based on privacy/endpoint config.

    Combines venv env (if enabled) with endpoint env (base_url, api_key).
    Returns None if using defaults (open, no venv).
    """
    import os

    from urika.core.venv import get_venv_env

    if runtime_config is None:
        runtime_config = load_runtime_config(project_dir)

    env = None

    # Start with venv env if enabled
    venv_env = get_venv_env(project_dir)
    if venv_env:
        env = dict(venv_env)

    # Determine which endpoint this agent should use
    agent_config = runtime_config.model_overrides.get(agent_name)
    endpoint_name = "open"
    if agent_config:
        endpoint_name = agent_config.endpoint
    elif runtime_config.privacy_mode == "private":
        endpoint_name = "private"
    elif runtime_config.privacy_mode == "hybrid":
        # Default hybrid: data_agent and tool_builder use private endpoint
        _PRIVATE_AGENTS = {"data_agent", "tool_builder"}
        if agent_name in _PRIVATE_AGENTS:
            endpoint_name = "private"

    if endpoint_name != "open":
        endpoint = runtime_config.endpoints.get(endpoint_name)
        if endpoint is None or not endpoint.base_url:
            # Hard fail — silently falling back to the cloud endpoint
            # would violate the privacy contract.  The user must
            # configure the endpoint before running privacy-sensitive
            # work.
            reason = (
                "is missing"
                if endpoint is None
                else "has no base_url"
            )
            raise MissingPrivateEndpointError(
                f"Privacy mode '{runtime_config.privacy_mode}' "
                f"requires the '{endpoint_name}' endpoint to be "
                f"configured for agent '{agent_name}', but "
                f"[privacy.endpoints.{endpoint_name}] {reason}. "
                f"Configure it in this project's urika.toml, in the "
                f"global ~/.urika/settings.toml, or via `urika config` "
                f"or the dashboard's Privacy tab before running this "
                f"project."
            )
        if endpoint:
            if env is None:
                env = dict(os.environ)
            if endpoint.base_url:
                env["ANTHROPIC_BASE_URL"] = endpoint.base_url
                # Disable beta headers that local servers reject
                env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] = "1"
            # v0.4.1: declare context window + output cap to the bundled
            # claude CLI. Without these, the CLI defaults to a 32K
            # output request which alone fills a 32K-window vLLM
            # endpoint and yields HTTP 400 ContextWindowExceededError.
            # Auto-defaults via ``resolve_endpoint_limits``: cloud
            # endpoints get 200K/32K (no behaviour change), local /
            # private endpoints get 32K/8K conservative bounds. Users
            # override per-endpoint in urika.toml or settings.toml.
            cw, mo = resolve_endpoint_limits(endpoint)
            env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(cw)
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(mo)
            # Auth-header selection for non-Anthropic endpoints. The
            # bundled Claude Agent SDK CLI sends:
            #   ANTHROPIC_API_KEY   -> header ``x-api-key: <key>``
            #   ANTHROPIC_AUTH_TOKEN -> header ``Authorization: Bearer <token>``
            # api.anthropic.com expects the former; vLLM / LiteLLM /
            # OpenRouter / most OpenAI-compatible private endpoints
            # expect the latter (and reject ``x-api-key`` with a 401
            # "Ensure Key has 'Bearer ' prefix"). Detect non-Anthropic
            # base_urls and set the auth-token form instead.
            is_anthropic = "anthropic.com" in (endpoint.base_url or "").lower()
            if endpoint.api_key_env:
                key = os.environ.get(endpoint.api_key_env, "")
                if key:
                    if is_anthropic:
                        env["ANTHROPIC_API_KEY"] = key
                        env.pop("ANTHROPIC_AUTH_TOKEN", None)
                    else:
                        # OpenAI-compatible endpoint — Bearer-token
                        # auth. Clear ANTHROPIC_API_KEY so the SDK
                        # doesn't double-send the conflicting header.
                        env["ANTHROPIC_AUTH_TOKEN"] = key
                        env.pop("ANTHROPIC_API_KEY", None)
                elif _is_local_endpoint(endpoint.base_url):
                    env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
                    env.pop("ANTHROPIC_API_KEY", None)
            elif _is_local_endpoint(endpoint.base_url):
                env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
                env.pop("ANTHROPIC_API_KEY", None)

    return env


def _is_local_endpoint(url: str) -> bool:
    """Check if a URL points to a local server (Ollama, LM Studio, etc.)."""
    if not url:
        return False
    return (
        "localhost" in url
        or "127.0.0.1" in url
        or "0.0.0.0" in url
    )


def get_agent_model(agent_name: str, runtime_config: RuntimeConfig) -> str | None:
    """Get the model override for a specific agent, or None for default."""
    agent_config = runtime_config.model_overrides.get(agent_name)
    if agent_config and agent_config.model:
        return agent_config.model
    return runtime_config.model or None


@dataclass
class AgentRole:
    """Definition of an agent role."""

    name: str
    description: str
    build_config: Callable[..., AgentConfig]
