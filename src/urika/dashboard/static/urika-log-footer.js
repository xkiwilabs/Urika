// Live footer for log pages. Updates:
// - elapsed: ticks every second from page-load
// - agent: parsed from agent-header SSE lines (uses urikaClassifyLine result)
// - tokens / cost: polled from /api/projects/<n>/usage/totals every 5s
// Footer fields are unset (—) when no data is available yet.

(function () {
  const projectName = document.body.dataset.projectName;
  if (!projectName) return;
  const footer = document.querySelector("[data-log-footer]");
  if (!footer) return;

  // Elapsed timer
  const elapsedEl = footer.querySelector("[data-footer-elapsed]");
  const startedAt = Date.now();
  function fmtElapsed(ms) {
    const total = Math.floor(ms / 1000);
    const m = String(Math.floor(total / 60)).padStart(2, "0");
    const s = String(total % 60).padStart(2, "0");
    return `${m}:${s}`;
  }
  if (elapsedEl) {
    setInterval(() => {
      elapsedEl.textContent = fmtElapsed(Date.now() - startedAt);
    }, 1000);
  }

  // Agent + model: hook into the log container's mutation observer so
  // any new line that arrives via the SSE handler triggers reclassify.
  //
  // Pre-fix the agent regex anchored at ^─── which expected the line
  // to LITERALLY start with "───". cli_display.print_agent prefixes
  // every agent header with two spaces ("\n  ─── Planning Agent ───…")
  // so the start anchor never matched and the footer agent + model
  // fields stayed at "—" forever, even with ANSI colour codes
  // disabled. Fix: strip ANSI escapes + leading whitespace before
  // matching. Also widened the model regex to recognise local-model
  // formats (qwen2.5:14b, llama-3.2:8b) used by private endpoints.
  const agentEl = footer.querySelector("[data-footer-agent]");
  const modelEl = footer.querySelector("[data-footer-model]");
  // ANSI CSI escape sequence regex — matches \x1b[<digits>;…m
  const ANSI_RE = /\x1b\[[0-9;]*m/g;
  const log = document.getElementById("log");
  if (log) {
    const obs = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          // textContent strips browser-rendered escapes, but the SSE
          // payload arrives as raw text (we set textContent directly
          // in the run-log handler), so ANSI codes survive the trip
          // when stdout was a TTY at orchestrator-spawn time.
          const raw = node.textContent || "";
          const text = raw.replace(ANSI_RE, "").trimStart();

          // "─── Planning Agent ───…", "─── Tool Builder ───…",
          // "─── Finalizer ───…" — optional " Agent" suffix.
          const agentMatch = text.match(/^─── ([\w ]+?)(?: Agent)? ─/);
          if (agentMatch && agentEl) {
            agentEl.textContent = agentMatch[1].toLowerCase();
          }
          // Model spotted anywhere in the line — first match wins per
          // line; the latest match across lines wins overall, which is
          // what we want when an agent switches model mid-experiment
          // (reasoning/execution split case).
          const modelMatch = text.match(
            /\b(claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+|gemini-[a-z0-9.-]+|qwen[a-z0-9.:_-]+|llama[a-z0-9.:_-]+|mistral[a-z0-9.:_-]+)\b/i
          );
          if (modelMatch && modelEl) {
            modelEl.textContent = modelMatch[1];
          }
        }
      }
    });
    obs.observe(log, { childList: true });
  }

  // Tokens + cost: poll /api/projects/<n>/usage/totals
  const tokensEl = footer.querySelector("[data-footer-tokens]");
  const costEl = footer.querySelector("[data-footer-cost]");
  function fmtTokens(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(0) + "K";
    return String(n);
  }
  async function pollUsage() {
    if (document.hidden) return;
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(projectName)}/usage/totals`);
      if (!r.ok) return;
      const d = await r.json();
      const total = (d.tokens_in || 0) + (d.tokens_out || 0);
      if (tokensEl) tokensEl.textContent = fmtTokens(total);
      if (costEl) costEl.textContent = `$${(d.cost_usd || 0).toFixed(2)}`;
    } catch (_) { /* network blip; try next tick */ }
  }
  pollUsage();
  setInterval(pollUsage, 5000);
})();
