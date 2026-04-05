/**
 * Urika TUI — Terminal UI + Adaptive Orchestrator
 *
 * Two modes:
 *   --interactive (default): pi-tui with conversational orchestrator
 *   --headless: stdout JSON events, no TUI
 */

const args = process.argv.slice(2);
const headless = args.includes("--headless");

if (headless) {
  console.log(JSON.stringify({ event: "started", mode: "headless" }));
} else {
  console.log("Urika TUI — not yet implemented");
}

process.exit(0);
