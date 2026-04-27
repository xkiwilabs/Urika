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
  const agentEl = footer.querySelector("[data-footer-agent]");
  const modelEl = footer.querySelector("[data-footer-model]");
  const log = document.getElementById("log");
  if (log) {
    const obs = new MutationObserver((mutations) => {
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (!(node instanceof HTMLElement)) continue;
          const text = node.textContent || "";
          // Re-run the classifier and extract the agent name
          const m2 = text.match(/^─── ([\w ]+?)(?: Agent)? ─/);
          if (m2 && agentEl) {
            agentEl.textContent = m2[1].toLowerCase();
          }
          const modelMatch = text.match(/\b(claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+|gemini-[a-z0-9.-]+|qwen[a-z0-9.-]+)\b/i);
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
