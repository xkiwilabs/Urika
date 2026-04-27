// urika-active-ops-poll.js — periodically check the project's running
// ops; when the set changes (op started OR completed), reload the page
// so banner chips + button states reflect current reality.
//
// Triggered on every project-scoped page (we detect this by reading
// data-project-name from <body>). On global pages the script is a
// no-op.

(function () {
  const POLL_INTERVAL_MS = 5000;

  const projectName = document.body.dataset.projectName;
  if (!projectName) return;  // global page; nothing to poll

  const url = "/api/projects/" + encodeURIComponent(projectName) + "/active-ops";

  // Compute a stable signature: sorted "type|experiment_id" strings
  // so reordering by the server doesn't trigger a spurious reload.
  function signature(ops) {
    return ops
      .map((op) => op.type + "|" + (op.experiment_id || ""))
      .sort()
      .join(",");
  }

  let lastSig = null;

  async function tick() {
    if (document.hidden) return;  // pause when tab is hidden
    try {
      const r = await fetch(url, { headers: { "Accept": "application/json" } });
      if (!r.ok) return;
      const ops = await r.json();
      const sig = signature(ops);
      if (lastSig !== null && sig !== lastSig) {
        // The set changed — re-render the page so banner + buttons
        // catch up. Plain reload is brute-force but predictable; we
        // don't have to reason about partial DOM swaps for every
        // running-state surface.
        window.location.reload();
        return;
      }
      lastSig = sig;
    } catch (_e) {
      // Network blip — skip this tick, try again next interval.
    }
  }

  // First tick computes the initial signature; subsequent ticks compare.
  tick();
  setInterval(tick, POLL_INTERVAL_MS);
})();
