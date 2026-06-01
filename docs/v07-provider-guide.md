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
| Cost-sensitive batch work | OpenAI `gpt-5.4-mini` or Google `gemini-3-flash` | ~5× cheaper per 1M tokens than Opus / GPT-5.4-pro |
| Lowest latency | Google `gemini-3-flash` | Fastest first-token in our smoke runs |
| Long-context reasoning | Anthropic `claude-opus-4-7` | Largest stable context window + strongest design-rationale generation |
| Tool-heavy execution loops | OpenAI Agents SDK | Most polished function-calling surface in our tests |
| Native subscription auth | Anthropic | Only provider with subscription-mode auth (Pro / Max) |

When in doubt, leave the default (Anthropic Opus for the four
reasoning agents, Sonnet 4.5 for the eight execution agents) —
that's the cost/quality sweet-spot the v0.4.0 work landed on, and
it's the configuration every other Urika user is running.

## Auth setup per provider

Every provider supports API-key auth. Anthropic additionally
supports subscription auth (opt-in, post-June 15 2026).

```bash
# Anthropic — API key (default)
urika config anthropic --mode api_key

# Anthropic — subscription (requires `claude login` first)
urika config anthropic --mode subscription

# OpenAI
urika config openai --mode api_key

# Google
urika config google --mode api_key
```

The wizard saves API keys to the vault under the canonical secret
name (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`)
and writes the `[<provider>] auth = "..."` toggle to
`~/.urika/settings.toml`. You can verify with `urika config
<provider> --test`.

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
model = "gemini-3-pro"           # Google for between-experiment analysis

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

Gemini prices in `urika.agents.pricing.PRICES` ship as
placeholders against Google's published rates — verify them
against [ai.google.dev/pricing](https://ai.google.dev/pricing)
before depending on a cost estimate for budgeting.
