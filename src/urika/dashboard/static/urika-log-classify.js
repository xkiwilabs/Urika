// Per-line classifier for the streaming log pages.
// Inspects the line text and returns a CSS class to apply, or null.
// Pure pattern-matching — no DOM changes here.

const AGENT_PATTERNS = [
  [/^─── Planning Agent ─/, "log-line--planning"],
  [/^─── Task Agent ─/, "log-line--task"],
  [/^─── Evaluator ─/, "log-line--evaluator"],
  [/^─── Advisor Agent ─/, "log-line--advisor"],
  [/^─── Report Agent ─/, "log-line--report"],
  [/^─── Presentation Agent ─/, "log-line--presentation"],
  [/^─── Tool Builder ─/, "log-line--tool-builder"],
  [/^─── Data Agent ─/, "log-line--data"],
  [/^─── Literature Agent ─/, "log-line--literature"],
  [/^─── Project Builder ─/, "log-line--project-builder"],
  [/^─── Project Summarizer ─/, "log-line--summarizer"],
  [/^─── Finalizer ─/, "log-line--finalizer"],
];

const BANNER_CHARS = /^[╭│╰║╔╚═█╗╝▀]/;
const GENERIC_HEADER = /^─── .+ ─/;

function urikaClassifyLine(text) {
  if (BANNER_CHARS.test(text)) return "log-line--banner";
  for (const [re, cls] of AGENT_PATTERNS) {
    if (re.test(text)) return cls;
  }
  if (GENERIC_HEADER.test(text)) return "log-line--agent";
  return null;
}

window.urikaClassifyLine = urikaClassifyLine;
