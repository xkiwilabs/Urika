# Prompt assembly bloat + context-window budget

**Status:** Planned for v0.4.1.
**Surfaced by:** v0.4 E2E private-mode smoke (2026-05-02). The user's
private vLLM endpoint (Qwen-class, 32K total context window) returned
HTTP 400 `ContextWindowExceededError` from the meta-orchestrator's
advisor: prompt was 94005 chars (~23K tokens), and the bundled CLI
also requested 32000 output tokens. 23K input + 32K output > 32K
total → instant 400. Cloud (200K-window) users don't see this but
they pay for the bloat in input-token cost.

**Root insight:** the 94K prompt is unreasonably large *regardless of
endpoint*. For a fresh-ish project at experiment 0, the advisor's
prompt should be ~15–20K chars. The 94K is a sign of redundant
assembly, not a context-window edge case.

---

## Three layers, in priority order

### Layer 1 — Trim prompt assembly (P0 for v0.4.1)

**Cost:** ~1 dev-day. **Affects:** every model, every endpoint.

Audit every prompt-builder site and find duplications. Rough hit list:

- **`methods.json` + `advisor-history.json`** both narrate "what
  was tried". Pick one as the canonical source for the advisor's
  context; reference the other by pointer ("see methods.json for
  full per-method metrics"). The advisor doesn't need both.
- **`advisor-context.md` rolling summary + full `advisor-history.json`**.
  The whole point of the rolling summary is to compress the history.
  Currently we inject *both*. Pick rolling summary by default; pass
  the full history only when explicitly requested
  (`urika advisor --full-history`).
- **Knowledge-store dump.** `KnowledgeStore` content is currently
  injected wholesale into the planner / advisor system prompts.
  Should be search-by-relevance against the current question (top-3
  matches by keyword/semantic search), not the full corpus.
- **Dataset profile + sample.** `inspect`-style profile + first 10
  rows of every column. 3 sample rows is plenty for the model to
  grasp shape; the full sample sits at 5–10K chars.
- **System-prompt redundancy.** Every role's system prompt embeds
  data-handling instructions, hardware summary, output-hygiene
  guidance, and the project description. Some of this overlaps
  between roles. Could be deduplicated via a shared preamble that
  isn't reinjected per call.

Audit method:

```python
# Instrument each role's build_config to log prompt-section sizes.
# After running a representative project, dump:
#   role               | system | memory | history | methods | profile | knowledge | total
#   advisor_agent      |  4321  |  2103  |  9421   |  3210   |  6710   |  47200    | 73K
#   planning_agent     |  3892  |  2103  |  0      |  3210   |  6710   |  47200    | 63K
#   ...
# The hot spots become obvious.
```

Acceptance: a fresh-project-at-experiment-0 advisor prompt
produces < 25K chars. A 5-experiments-deep advisor prompt
produces < 40K chars.

### Layer 2 — Per-endpoint context_window declaration + output clamp (P0 for v0.4.1)

**Cost:** ~0.5 dev-day. **Affects:** private-mode users immediately;
cloud users transparently.

Add to `[privacy.endpoints.<name>]` in `~/.urika/settings.toml`:

```toml
[privacy.endpoints.private-vllm-large]
base_url = "http://100.127.175.6:4200"
api_key_env = "INFERENCE_HUB_KEY"
default_model = "large"
context_window = 32768           # NEW
max_output_tokens = 8000         # NEW (optional; defaults to 25% of context_window)
```

Plumb both fields through `urika.agents.config.AgentConfig` and
into the SDK options. The bundled CLI accepts `--max-tokens N`
(or via `ClaudeAgentOptions(max_tokens=N)`); use it.

Sane defaults when the fields aren't declared:

- `api.anthropic.com` URLs → context_window 200000, max_output 32000.
- Private/local URLs → context_window 32768, max_output 8000
  (conservative, leaves 24K for input).
- Override allowed per-endpoint and per-agent.

Acceptance: the v0.4 E2E private-mode smoke completes the
meta-orchestrator's advisor without a 400. The user's vLLM
endpoint stops 400-ing on Layer 1 + Layer 2 alone.

### Layer 3 — Summarisation fallback (P2 for v0.5)

**Cost:** ~2 dev-days. **Use sparingly.**

After Layers 1 + 2, a long-running project (months of advisor
exchanges, dozens of experiments) might still bust the budget. At
that point, summarise the longest *mutable* section automatically:

- Advisor history → fold into rolling summary, drop the oldest N
  exchanges from the raw history.
- Knowledge-store relevance → narrow the top-3 to top-1 with an
  expanded summary.
- Methods registry → group "tried and rejected" methods into a
  one-paragraph block.

**Critical constraint:** summarisation is lossy. The advisor needs
*concrete numbers* to recommend *concrete next steps*. A summary of
"tried 3 regression methods, best R²=0.85" loses the per-method
nuance the advisor would otherwise notice. Only summarise when
forced; surface the trade-off to the user when it triggers.

Use a small/fast model for the summarisation pass (haiku, or a
cheap local model if private). Don't recurse on the user's main
expensive model.

Acceptance: a project with > 20 experiments still fits in a 32K
context window. Summarisation events are logged to
`projectbook/.urika/summarisation.log` so the user can audit what
was compressed.

---

## What we are NOT building

- **Per-mode branched code paths.** A "private-only summarisation
  layer" would diverge from cloud and rot. Keep one assembly path,
  parametrise its budget.
- **An auto-prompt-tuner.** No ML over the prompt. Static, declarative
  trim rules + per-endpoint declarations.
- **Smaller default Anthropic models.** Cloud users have 200K+
  windows; we do not need to ration aggressively. The Layer-1 trim
  helps them via lower input-token cost, that's enough.

---

## Sequencing

1. v0.4.1: Layer 1 + Layer 2.
2. v0.5: Layer 3 if real-world projects still bust budgets after
   Layer 1 + 2 in production.

The Layer-1 audit happens first — without it we cannot know how
much pure trimming gains us, and Layer 3 is wasted work if Layer 1
solves the problem on its own.

## Tracking

This plan supersedes the user's question
(2026-05-02 conversation): *"should we add a per-endpoint
summarisation layer, or is this a more general memory and token
management issue?"* — answer: it's general; private mode just
exposed it; fix in shared code.
