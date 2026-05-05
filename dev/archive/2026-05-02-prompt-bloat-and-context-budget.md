# Prompt assembly bloat + context-window budget

**Status:** Re-scoped 2026-05-02 after data collection. Layer 1 (trim)
is **NOT shipping in v0.4.1** — trace evidence shows the SDK's
bundled CLI is amortising input via prompt caching at 75–93% per
agent, making input-token cost negligible for cloud users. Layer 2
(per-endpoint `context_window` + `max_output_tokens` declaration)
remains P0 for v0.4.1 because it addresses the actual failure mode
for local/private endpoints. Layer 3 deferred to v0.5.

**Surfaced by:** v0.4 E2E private-mode smoke (2026-05-02). The user's
private vLLM endpoint (Qwen-class, 32K total context window) returned
HTTP 400 `ContextWindowExceededError` from the meta-orchestrator's
advisor: prompt was 94005 chars (~23K tokens), and the bundled CLI
also requested 32000 output tokens. 23K input + 32K output > 32K
total → instant 400.

**Diagnostic data collected:** `URIKA_PROMPT_TRACE_FILE` instrumentation
(committed 7ab30ef8) ran across a real co2-emissions-analysis run on
the cloud Anthropic API. Findings:

| Agent | Cache hit % | Avg fresh input tokens | Avg output tokens |
|---|---|---|---|
| advisor_agent | 81.0 | 18 | 4,822 |
| evaluator | 75.5 | 35 | 10,715 |
| planning_agent | 84.7 | 12 | 6,896 |
| task_agent | 93.7 | 158 | 21,904 |
| **Overall** | **89.0** | **mean 53** | **mean 10,234** |

Of 6.2M total input tokens accumulated across 13 calls, only **686
were freshly billed**. The rest were 90% cache reads + 11%
write-once cache creations. **Output tokens (133K total) outweigh
fresh input tokens by 194:1.**

The 94K-char prompt that triggered the original bug was specific to
the **meta-orchestrator's `_determine_next` advisor**, which slices
`methods[-20:]`, `criteria.criteria[:500]`, `experiments[-10:]` —
for a project with 20+ methods and 10+ experiments these slices
balloon. The inner-loop advisor (instrumented above) stays at
1–8 KB even at experiment 11. So the trim work, if needed at all,
is confined to one specific call site, not "every prompt-builder".

---

## Three layers — revised priorities

### ~~Layer 1 — Trim prompt assembly~~ (DEPRIORITISED)

**Original premise:** input-token cost grows with project age and
trimming would save money.

**What the trace shows:** for cloud Anthropic, input-token cost is
amortised at 89% via the bundled CLI's prompt caching. Trimming
30–50% of the user prompt would save roughly _50–100 fresh input
tokens per turn_ against a stream of _21,000 output tokens per
turn_. Not a meaningful lever.

**Where it might still matter (and would need targeted work, not
a global trim):**

* **Meta-orchestrator's `_determine_next` advisor** at experiment
  10+. The slice caps (`methods[-20:]`, `experiments[-10:]`) hit
  full-fat content and produce the 94K-char prompts that broke
  private-mode. Replace with a "summary line per method" + an
  on-demand pointer to disk for the few methods the advisor wants
  to inspect deeply.
* **Local-model context windows.** Caching is an Anthropic-API
  billing optimisation; vLLM / LiteLLM / OpenRouter endpoints don't
  see cache reads as anything different from fresh input — the
  full prompt hits the model's 32K window every call. So _for
  local models the prompt size still matters._ But the inner-loop
  prompts measured by the trace (max 20 KB on task_agent ≈ 5K
  tokens, +7 KB system ≈ 1.7K tokens) are well under any
  realistic local-model window. Layer 2 + the meta-orchestrator
  trim above are sufficient.

**Action:** open a separate, narrowly-scoped ticket for the
meta-orchestrator advisor specifically when a real project hits it.
Do NOT do a global "audit every prompt-builder" pass — the data
says it's wasted work.

### Layer 2 — Per-endpoint context_window declaration + output clamp (P0 for v0.4.1)

**Cost:** ~0.5 dev-day. **Affects:** private-mode users immediately;
cloud users transparently.

This stays. It is the **actual fix** for the original
ContextWindowExceededError. The bundled CLI requests 32K output
tokens by default, which alone fills a 32K-window vLLM endpoint.

Add to `[privacy.endpoints.<name>]` in `~/.urika/settings.toml`:

```toml
[privacy.endpoints.private-vllm-large]
base_url = "http://100.127.175.6:4200"
api_key_env = "INFERENCE_HUB_KEY"
default_model = "large"
context_window = 32768           # NEW
max_output_tokens = 8000         # NEW (defaults to 25% of context_window)
```

Plumb both fields through `urika.agents.config.AgentConfig` and
into the SDK options via `ClaudeAgentOptions(max_tokens=N)`.

Sane defaults when fields aren't declared:

* `api.anthropic.com` URLs → `context_window=200000`,
  `max_output_tokens=32000` (preserves current cloud behaviour).
* Private/local URLs → `context_window=32768`, `max_output_tokens=8000`
  (conservative; leaves 24K for input).
* Override allowed per-endpoint and per-agent.

**Acceptance:** the v0.4 E2E private-mode smoke completes the
meta-orchestrator's advisor without a 400. The user's vLLM endpoint
stops 400-ing on Layer 2 alone.

### Layer 3 — Summarisation fallback (deferred to v0.5)

Unchanged from original. After Layer 2, if a long-running project
(months of advisor exchanges, dozens of experiments) still busts
the budget, summarise the longest mutable section automatically.
**Critical constraint** still holds: summarisation is lossy; only
trigger when forced and surface the trade-off to the user.

---

## What we are NOT building

* **A global prompt-builder audit.** Trace data killed the
  hypothesis. Targeted trim (meta-orchestrator advisor) is the
  only place where input bloat appears in practice.
* **Per-mode branched code paths.** Keep one assembly path,
  parametrise its budget via Layer 2.
* **An auto-prompt-tuner.** No ML over the prompt. Static,
  declarative trim rules + per-endpoint declarations.
* **Smaller default Anthropic models.** Cloud users have 200K+
  windows and amortised input cost.

---

## What this redirects attention to

The trace surfaced two real cost / runtime drivers that aren't on
the v0.4.1 list yet:

1. **Output verbosity.** task_agent averages ~22K output tokens per
   call. Output is unambiguously where the bill is. A
   prompt-instruction nudge ("be concise; metrics first; one
   paragraph of commentary max") could halve this without losing
   substance. v0.5 candidate, evidence-backed.
2. **Per-call wall time.** task_agent p95 is 397s (6.6 min).
   That's not a prompt problem — it's an agent-doing-real-work
   problem. The right knob is **v0.4.1 #4 (per-tool-call Bash
   timeout)** plus the **long-running training cookbook**
   (v0.4.1 #5, shipped b131f013).

---

## Sequencing

1. **v0.4.1: Layer 2 only.** Per-endpoint context_window /
   max_output_tokens declarations. ~0.5 dev-day.
2. **v0.4.1 #4 (Bash timeout) becomes higher priority** since it
   targets the real cost driver (task runtime).
3. **v0.4.2 / v0.5 candidate:** narrow trim of the
   meta-orchestrator advisor _if_ a real project trips it after
   Layer 2 ships.
4. **v0.5: Layer 3** if needed in production after Layer 2.

## Tracking

- Original concern: "prompts grow turn-over-turn" — partially
  correct (knowledge re-prefix, advisor suggestion relay) but
  the cache amortises 89% of it. The user-facing cost effect
  is small.
- Investigated 2026-05-02 with live data; this plan rewritten
  to reflect findings.
- Trace tool: `dev/scripts/analyze_prompt_trace.py` reads the
  JSONL output of `URIKA_PROMPT_TRACE_FILE` and reproduces the
  per-agent table above. Use when re-evaluating in future
  releases.
