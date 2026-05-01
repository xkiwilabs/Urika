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

Urika is provider-agnostic by design — it routes agent calls through whichever model SDK the project's privacy mode and agent config specify. v0.4 ships with one fully-supported adapter (Anthropic's Claude Agent SDK); additional adapters can be added through the `urika.runners` Python entry-point group (see [Contributing an Adapter](contributing-an-adapter.md)). Each provider has its own terms of service and its own compliant authentication pattern. Urika's job is to enforce the right pattern per provider.

### Are we using the Anthropic SDK in a sanctioned way?

Yes. Urika uses [`claude-agent-sdk-python`](https://github.com/anthropics/claude-agent-sdk-python), the official Anthropic Python wrapper, exactly as documented at [code.claude.com/docs/en/agent-sdk/overview](https://code.claude.com/docs/en/agent-sdk/overview). The SDK spawns the `claude` CLI as a subprocess; we set `ANTHROPIC_API_KEY` so the CLI uses metered API authentication; we actively scrub OAuth tokens from the subprocess environment to prevent any subscription leakage.

The April 2026 enforcement targeted tools that *reverse-engineered* the OAuth flow to piggyback on subscription quotas (OpenClaw, NanoClaw, OpenCode). Urika does the opposite — uses the official SDK with metered API and blocks the OAuth path.

### Anthropic's terms

Anthropic's [Consumer Terms of Service §3.7](https://www.anthropic.com/legal/consumer-terms)
prohibits accessing Claude through automated or non-human means except via
official API keys. The April 2026 Agent SDK clarification was explicit:
"Using OAuth tokens obtained through Claude Free, Pro, or Max accounts in
any other product, tool, or service — including the Agent SDK — is not
permitted."

**What this means for Urika:**

- **Use an API key** (`ANTHROPIC_API_KEY`) for any `urika` command. This
  is the only compliant path.
- **A Pro / Max subscription does not authorise running Urika**, even for
  development or testing. The subscription remains valid for direct
  interactive use of Claude.ai or the `claude` CLI by a human.
- Urika prints a one-time warning at startup when `ANTHROPIC_API_KEY` is
  unset, and the dashboard's Settings page surfaces the same warning as
  a banner.

**For developers contributing to Urika:**

- Editing the codebase from Claude Code (interactive coding) on a Pro/Max
  plan is permitted — that's official tool, human-in-the-loop usage.
- Running the test suite or any `urika` command requires an API key — the
  test suite spawns Urika subprocesses which use the Agent SDK.

If you have questions about acceptable use, contact Anthropic.

### How Urika enforces this

Urika's safety net is three layers deep — the Pro/Max subscription
cannot be used even by accident:

1. **CLI startup warning.** When `ANTHROPIC_API_KEY` is unset, every
   `urika` invocation prints a yellow warning at startup pointing to
   `urika config api-key`. Dismiss permanently with
   `URIKA_ACK_API_KEY_REQUIRED=1`.

2. **Pre-spawn refusal.** Before spawning a Claude Agent SDK
   subprocess, Urika checks that an API key is configured. If no key
   is found and the agent is bound for `api.anthropic.com`, the run
   aborts with `APIKeyRequiredError` and a remediation hint.

3. **OAuth env scrubbing.** Even if the user has
   `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_AUTH_TOKEN` set in their
   shell, Urika scrubs both variables (sets them to empty) in the
   environment passed to the spawned subprocess. The Claude CLI then
   has no OAuth credential available — it must use the API key or
   fail loudly.

The pre-spawn check is exempt for:
- Agents configured with `ANTHROPIC_BASE_URL` (going to a private
  inference endpoint, not Anthropic's cloud).
- Models that don't start with `claude` (a future multi-provider
  runtime routes them to a different SDK).

Source: `src/urika/core/compliance.py`.

### Other providers (planned)

When OpenAI, Google ADK, and PI adapters land, the same compliance pattern applies:

- **OpenAI** (planned) — uses [`openai-agents-python`](https://github.com/openai/openai-agents-python), pure HTTP, no CLI. Requires `OPENAI_API_KEY`. OpenAI's Usage Policies and API Terms of Service govern programmatic use.
- **Google ADK** (planned) — uses Google's Agent Development Kit, pure Python. Requires `GOOGLE_API_KEY` or service-account credentials. Governed by Google Cloud's Generative AI Acceptable Use Policy.
- **PI** (planned) — uses PI's runtime; specifics TBD.
- **Local / private endpoints** — direct HTTP via `ANTHROPIC_BASE_URL` to Ollama / vLLM / LiteLLM. No cloud-provider CLI or API key needed; governed only by your local infrastructure's security posture.

Each adapter will surface its own per-provider compliance check — same shape as `require_api_key()` for Anthropic, scoped to whichever credentials and runtime that provider expects.
