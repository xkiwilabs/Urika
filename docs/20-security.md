# Security Model

Urika is a local research tool that runs agent-written code on your behalf. This document describes what that means for security and how the trust boundaries are drawn.

## Agent-generated code runs as you

The task agent, finalizer, and tool builder write Python code into your project directory and execute it via `subprocess.run([sys.executable, ...])`. **There is no sandbox.** Generated code runs with the same filesystem access, environment variables, and network permissions as the process that launched `urika run`.

### What this means in practice

- **Inspect before rerunning.** Each experiment's generated method scripts live under `<project>/experiments/<id>/methods/` (the task agent can also write artefacts elsewhere within the experiment dir). Read them before re-running an experiment or sharing the project with a collaborator.
- **Use `--dry-run` to preview.** `urika run --dry-run` prints the planned pipeline — which agents will run, which directories are writable, where task-agent Python will land — without invoking any agent. Use it when you want to know what's about to happen before it does.
- **Don't run untrusted projects.** If someone sends you a Urika project directory, treat it like running a random Python script from that person. Agent-written code committed to the project can and will execute on `urika run`.
- **Avoid shared hardware.** Do not run Urika on a machine where the user you're logged in as can write to files other users depend on. The agent's filesystem access is your user's filesystem access.

## Permission boundaries

Each agent role declares its own `SecurityPolicy` when invoked:

| Field | What it controls |
|-------|------------------|
| `readable_dirs` | Directories the agent may read |
| `writable_dirs` | Directories the agent may write to |
| `allowed_tools` / `disallowed_tools` | Which Claude Code tools the agent may use |
| `allowed_bash_prefixes` | Bash command prefixes allowed (e.g. `"urika "`) |
| `blocked_bash_patterns` | Bash fragments that are refused even if the prefix matches |

**v0.4 enforces these policies at runtime** via the SDK's `can_use_tool` callback (see `urika/agents/permission.py`): every tool dispatch is intercepted and the agent receives an explicit deny message — including a reason — when a request escapes the policy. Pre-v0.4 the same fields were declared but advisory only. Path checks resolve symlinks and `..` traversal before matching against `readable_dirs` / `writable_dirs`; Bash commands are tokenised with `shlex` and reject shell metacharacters (`;`, `&&`, `|`, `$(`, `` ` ``, redirections) outright before the prefix allowlist is consulted. If you need a stronger boundary still (untrusted projects, regulated data, multi-tenant hosts), run Urika inside a container or VM.

Concrete examples of the policies in effect:

- The **evaluator** is read-only: `allowed_tools=["Read", "Glob", "Grep"]`, `writable_dirs=[]`.
- The **presentation agent** cannot run code: `allowed_tools=["Read", "Glob", "Grep"]`, no Bash.
- The **task agent** can execute generated Python from `experiments/<id>/methods/` and write to the methods registry. The agent's writable scope is the entire `experiments/<id>/` subtree.
- The **orchestrator chat** can invoke subagents via `urika ` CLI prefixes through Bash, but is blocked from reading raw data files directly (`cat */data/`, `head */data/`, etc.).

## Secrets

Urika stores API keys and similar secrets in `~/.urika/secrets.env` with permissions `0600` (owner-only read/write). On CLI startup, entries are loaded into `os.environ` so downstream agents and SDKs can pick them up.

Precedence when the same secret is defined in multiple places: CLI argument → environment variable → `secrets.env`.

- **Do** keep API keys in `~/.urika/secrets.env`. It is not tracked by git.
- **Don't** commit secrets to a project directory or export them in shell rc files the whole system reads.
- **Consider** integrating with an OS keyring (`keyring` package) if you share a machine. Not the default, but supported via the standard environment-variable interface.

## Dashboard

`urika dashboard` binds to `127.0.0.1` (localhost only). The default port is a random free port chosen at startup and printed on the console; override with `--port`. Directory traversal is prevented by an `is_relative_to(project_dir)` check on every served path.

**Authentication is opt-in.** Without `--auth-token`, anyone with shell access to the machine — and, over SSH forwarding, anyone who can tunnel to the chosen port — can browse the dashboard. To require a bearer token on every request, pass `--auth-token <secret>` (or set `URIKA_DASHBOARD_AUTH_TOKEN`). For networked use, put it behind an auth proxy (Caddy, nginx, Tailscale) rather than exposing it directly.

## Notifications

The Slack and Telegram notification channels send alerts *out* from your Urika instance. They also optionally accept button-click interactions *in* (pause/stop/resume).

- **Slack interactions** arrive via Slack's Socket Mode. Block any untrusted channels or users by configuring `allowed_channels` / `allowed_users` in your Slack channel config. Without an allowlist, any user in the workspace who sees the bot can click its buttons.
- **Telegram interactions** arrive over a long-poll bot connection. Restrict to your own Telegram user ID.

If you deploy notifications for a team, audit the channel/user configuration before going live.

## Network

Urika itself makes no outbound network calls beyond:
- The Claude Agent SDK / LiteLLM calls your configured LLM providers (required for agents to function).
- The optional Slack and Telegram channels (only if enabled).
- The Literature Agent's PDF/URL fetches (only if invoked).
- `pip install` during first-time setup (only if triggered).

Agent-written code can obviously call whatever it likes. See the first section.

## Reporting security issues

Please report security issues privately to michael.j.richardson@mq.edu.au rather than filing a public GitHub issue.

## Provider compliance

Urika is provider-agnostic by design — it routes agent calls through whichever model SDK the project's privacy mode and agent config specify. As of v0.7.0 three adapters are first-class (Anthropic's Claude Agent SDK, the OpenAI Agents SDK, and Google's ADK); additional adapters can be added through the `urika.runners` Python entry-point group (see [Contributing an Adapter](contributing-an-adapter.md)). Each provider has its own terms of service and its own compliant authentication pattern. Urika's job is to enforce the right pattern per provider.

### Are we using the Anthropic SDK in a sanctioned way?

Yes. Urika uses [`claude-agent-sdk-python`](https://github.com/anthropics/claude-agent-sdk-python), the official Anthropic Python wrapper, exactly as documented at [code.claude.com/docs/en/agent-sdk/overview](https://code.claude.com/docs/en/agent-sdk/overview). The SDK spawns the `claude` CLI as a subprocess, and Urika supports both auth patterns Anthropic sanctions: metered API authentication via `ANTHROPIC_API_KEY` (the default), and — since June 15 2026 — subscription authentication via the Claude CLI's own `claude login` OAuth flow (opt-in).

The April 2026 enforcement targeted tools that *reverse-engineered* the OAuth flow to piggyback on subscription quotas (OpenClaw, NanoClaw, OpenCode). Urika does the opposite — it uses the official SDK, and in subscription mode the OAuth credential is the one the official CLI stores for itself; Urika never touches or replays it.

### Anthropic's terms: two auth modes

Urika supports two Anthropic auth modes, configured via
`[anthropic] auth` in `~/.urika/settings.toml` or
`urika config anthropic --mode ...`:

- **`api_key` (default)** — Urika calls `api.anthropic.com` using a
  standard `ANTHROPIC_API_KEY`. This is the original mode and stays the
  default, so existing users are never silently upgraded.
- **`subscription` (opt-in)** — legal since June 15 2026, when
  Anthropic's billing overhaul made Agent SDK workloads on Pro/Max
  subscriptions generally available. Agent SDK usage draws from a
  separate monthly **Agent credit pool** ($20 Pro / $100 Max-5x /
  $200 Max-20x, no rollover); requests stop when the pool is exhausted
  unless overage billing is enabled at API rates. Run `claude login`
  once to authenticate, then `urika config anthropic --mode subscription`.

Historical note: prior to June 15 2026, Anthropic's
[Consumer Terms of Service §3.7](https://www.anthropic.com/legal/consumer-terms)
and the April 2026 Agent SDK clarification prohibited the subscription
path ("Using OAuth tokens obtained through Claude Free, Pro, or Max
accounts in any other product, tool, or service — including the Agent
SDK — is not permitted"). Anthropic's May 13 2026 announcement legalised
it from June 15 onward, and Urika's enforcement layers below were
reframed accordingly.

**For developers contributing to Urika:** editing the codebase from
Claude Code (interactive coding) on a Pro/Max plan is, as ever,
ordinary human-in-the-loop usage. Running the test suite or any
`urika` command spawns Agent SDK subprocesses, so it needs whichever
auth mode you've configured — an `ANTHROPIC_API_KEY` in the default
mode, or a `claude login` session in subscription mode.

If you have questions about acceptable use, contact Anthropic.

### How Urika enforces this

Urika's safety net is three layers deep. In `api_key` mode the goal is
**billing hygiene** — a stray subscription credential must never
silently route charges to your Agent credit pool; in `subscription`
mode the OAuth credential is the legitimate auth carrier and is left
alone:

1. **CLI startup warning.** In `api_key` mode, when `ANTHROPIC_API_KEY`
   is unset, every `urika` invocation prints a yellow warning at
   startup pointing to `urika config api-key`. Dismiss permanently with
   `URIKA_ACK_API_KEY_REQUIRED=1`. Suppressed entirely in
   `subscription` mode (no API key is expected there).

2. **Pre-spawn refusal** (`api_key` mode only). Before spawning a
   Claude Agent SDK subprocess, Urika checks that an API key is
   configured. If no key is found and the agent is bound for
   `api.anthropic.com`, the run aborts with `APIKeyRequiredError` and a
   remediation hint. In `subscription` mode this check passes silently —
   the bundled CLI picks up its stored OAuth token from `claude login`.

3. **OAuth env scrubbing.** In `api_key` mode, Urika zeroes
   `CLAUDE_CODE_OAUTH_TOKEN` and the rest of the OAuth-token family in
   the environment passed to the spawned subprocess, so a stray
   parent-shell OAuth token cannot silently route charges to your
   subscription credit pool — the CLI must use the API key or fail
   loudly. In `subscription` mode the OAuth-token family is preserved
   (it is the legitimate credential). Nested-session markers (the env
   vars Claude Code sets in terminals it owns, which would make the
   spawned CLI refuse to launch) are always zeroed regardless of mode.

The pre-spawn check is exempt for:
- Agents configured with `ANTHROPIC_BASE_URL` (going to a private
  inference endpoint, not Anthropic's cloud).
- Models that don't start with `claude` (routed to a non-Anthropic
  provider via the multi-provider runtime).
- Users in `subscription` auth mode.

Source: `src/urika/core/compliance.py`.

### Other providers

The same compliance pattern applies per provider:

- **OpenAI** — uses [`openai-agents-python`](https://github.com/openai/openai-agents-python), pure HTTP, no CLI. Requires `OPENAI_API_KEY`; ChatGPT Plus subscriptions are a separate product and are rejected by `urika config openai --mode subscription`. OpenAI's Usage Policies and API Terms of Service govern programmatic use.
- **Google** — uses Google's Agent Development Kit, pure Python. Requires `GEMINI_API_KEY`; Google AI Pro/Ultra subscriptions are rejected (Google's Terms of Service forbid third-party SDK use). Governed by Google's Generative AI terms.
- **Local / private endpoints** — direct HTTP via `ANTHROPIC_BASE_URL` to Ollama / vLLM / LiteLLM. No cloud-provider CLI or API key needed; governed only by your local infrastructure's security posture.

Each adapter surfaces its own per-provider compliance check — same shape as `require_api_key()` for Anthropic, scoped to whichever credentials and runtime that provider expects.
