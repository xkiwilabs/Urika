# v0.7 Provider Guide

Urika v0.7.0 ships adapters for **Anthropic**, **OpenAI**, and
**Google**. You can pick one provider for the whole project or
mix-and-match per agent role. This guide answers the three
questions most users hit first.

## Which provider should I pick?

There is no objectively-best provider — each is better at
different things. The first-pass rubric:

| Use case | Recommended provider | Why |
|---|---|---|
| Default / unsure | Anthropic Claude | Most mature adapter, the original target, best test coverage |
| Cost-sensitive batch work | OpenAI `gpt-5.4-mini` (~3× cheaper than `gpt-5.4`) or Google `gemini-3.5-flash` | Lower per-1M-token rates than the reasoning tier |
| Lowest latency | Google `gemini-3.5-flash` | Fastest first-token in our smoke runs |
| Long-context reasoning | Anthropic `claude-opus-4-7` | Largest stable context window + strongest design-rationale generation |
| Tool-heavy execution loops | OpenAI Agents SDK | Most polished function-calling surface in our tests |
| Native subscription auth | Anthropic | Only provider with subscription-mode auth (Pro / Max) |

When in doubt, leave the default (Anthropic Opus for the four
reasoning agents, Sonnet 4.5 for the eight execution agents) —
that's the cost/quality sweet-spot the v0.4.0 work landed on, and
it's the configuration every other Urika user is running.

### Google Pro vs Flash — billing-only Pro

Unlike Anthropic and OpenAI, Google's v0.7.0 recommendation is
`gemini-3.5-flash` for **both** reasoning and execution roles.
`gemini-3.1-pro-preview` has a free-tier rate limit of 0 — it
requires a billing-enabled Google AI account, and recommending it
as the default would block free-tier users at first agent call.

If you have a billing-enabled Google account and want the Pro
quality for the four reasoning agents, override per-agent in your
project's `urika.toml`:

```toml
[runtime.models.planning_agent]
model = "gemini-3.1-pro-preview"

[runtime.models.advisor_agent]
model = "gemini-3.1-pro-preview"

[runtime.models.finalizer]
model = "gemini-3.1-pro-preview"

[runtime.models.project_builder]
model = "gemini-3.1-pro-preview"
```

Cost reporting works for these overrides — Pro rates are in
`urika.agents.pricing.PRICES`.

## Auth setup per provider

Every provider supports API-key auth. Anthropic additionally
supports subscription auth (opt-in, post-June 15 2026).

Setup is a **two-step** flow: first pin the auth mode, then
store the actual key. `urika config <provider>` only writes the
`[<provider>] auth = "..."` toggle to `~/.urika/settings.toml`
— it does **not** save the key itself.

### Step 1 — Pin the auth mode

```bash
# Anthropic — API key (default)
urika config anthropic --mode api_key

# Anthropic — subscription (requires `claude login` first)
urika config anthropic --mode subscription

# OpenAI (subscription not supported — OpenAI Plus is not the API)
urika config openai --mode api_key

# Google (subscription not supported — AI Pro/Ultra ToS forbids it)
urika config google --mode api_key
```

### Step 2 — Store the API key

The key goes into the secrets vault, which agents read at spawn
time. Vault storage is `~/.urika/secrets.env` by default, or the
OS keyring if you installed Urika with `pip install urika[keyring]`.

| Provider | Command | Canonical name |
|---|---|---|
| Anthropic | `urika config api-key` | `ANTHROPIC_API_KEY` |
| OpenAI | `urika config secret` | `OPENAI_API_KEY` |
| Google | `urika config secret` | `GEMINI_API_KEY` |

`urika config api-key` is the Anthropic-specific wizard (it
ignores any positional name argument). For OpenAI and Google use
`urika config secret`, which prompts you for the secret name
(enter the canonical name from the table above) and then for the
value.

> **Dashboard alternative:** the dashboard Settings page has a
> Secrets tab that stores the same vault entries via a form. See
> [Dashboard settings](18c-dashboard-settings.md) for the route.

### Step 3 — Verify

For Anthropic, the API-key wizard ships with a live-call probe:

```bash
urika config api-key --test
```

OpenAI and Google don't have a per-provider `--test` flag today
— the fastest end-to-end check is to set the matching mode in
`urika.toml` (or an experiment override) and run a one-shot
`urika run`; if the adapter can't authenticate the run fails
loudly with the provider's own error string.

## Mixing providers per agent role

The model string itself is the provider selector — Urika routes
`claude-*` to the Anthropic adapter, `gpt-*` / `o3-*` / `o4-*` /
`o5-*` to OpenAI, and `gemini-*` to Google. Set per-agent
overrides in your project's `urika.toml`:

```toml
[runtime]
model = "claude-opus-4-7"        # mode default (fallback)

[runtime.models.planning_agent]
model = "claude-opus-4-7"        # Anthropic for design-rationale

[runtime.models.task_agent]
model = "gpt-5.4-mini"           # OpenAI for cheap execution

[runtime.models.advisor_agent]
model = "gemini-3.5-flash"       # Google for between-experiment analysis
                                 # (use "gemini-3.1-pro-preview" if billing-enabled)

[runtime.models.evaluator]
model = "gpt-5.4-mini"           # OpenAI for cheap rule-application
```

The dashboard Models tab has a Provider filter that pre-populates
the per-agent dropdowns with each provider's recommended models —
the equivalent of the TOML above without hand-writing the keys.

**Caveat (v0.7.0 only):** the experiment loop is fully migrated to
per-agent routing, but ~20 support-agent call sites (`urika
advisor`, `urika finalize`, `urika report`, the memory curator,
some REPL chat paths) still hard-code the legacy `get_runner()`
factory. Until v0.7.1 hotfixes those, mixed-provider users get
correct routing on the planning → task → evaluator → advisor
cycle but silent Claude fallback on the standalone advisor /
finalize / report / curate commands.

## Cost reporting differences

API-key mode reports per-call $ cost via
`urika.agents.pricing.cost_for(model, in_tokens, out_tokens)`,
which is the same rate table for all three providers.
`urika usage`, the leaderboard, and the dashboard Usage page all
read this single source.

Subscription mode (Anthropic only) doesn't have a per-call $
figure — the subscription covers usage in flat-rate "credits". In
this mode the leaderboard and Usage page render "credits used"
instead of a dollar amount, and `cost_usd` in `AgentResult.usage`
is `0.0` with an explicit `usage["mode"] = "subscription"`
annotation so downstream tooling can tell the difference between
"unknown cost" and "subscription, $0 by design".

Gemini prices in `urika.agents.pricing.PRICES` were verified
against [ai.google.dev/pricing](https://ai.google.dev/pricing) on
2026-06-02. Both Gemini rows quote the ≤200k-token tier — Google
charges more for prompts above that threshold, so cost estimates
under-report for very long-context calls.
