import chalk from "chalk";
import { type Component, visibleWidth, truncateToWidth } from "@mariozechner/pi-tui";

// ── Token/cost/elapsed formatting ──

export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10000) return `${(n / 1000).toFixed(1)}k`;
  if (n < 1000000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1000000).toFixed(1)}M`;
}

export function formatCost(n: number): string {
  if (n < 0.01) return "$0.00";
  return `$${n.toFixed(2)}`;
}

export function formatElapsed(startMs: number): string {
  const sec = Math.floor((Date.now() - startMs) / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m${sec % 60}s`;
}

/** Mutable footer state — update fields directly. */
export interface FooterState {
  project: string;
  model: string;
  agent: string;
  tokensIn: number;
  tokensOut: number;
  cost: number;
  startTime: number;
  active: boolean;
}

/**
 * Dynamic footer component for agent TUI apps.
 * Displays: project, active agent, elapsed time, model, tokens, cost.
 *
 * Implements pi-tui's Component interface so it can be added directly
 * to a TUI container.
 */
export class FooterComponent implements Component, FooterState {
  project = "";
  model = "";
  agent = "";
  tokensIn = 0;
  tokensOut = 0;
  cost = 0;
  startTime = 0;
  active = false;

  invalidate(): void {}

  render(width: number): string[] {
    const D = chalk.dim;
    const sep = D(" · ");

    // Left side: project + agent activity
    const left: string[] = [];
    if (this.project) left.push(chalk.cyan(this.project));

    if (this.active) {
      if (this.agent) left.push(chalk.yellow(this.agent.replace(/_/g, " ")));
      if (this.startTime) left.push(D(formatElapsed(this.startTime)));
    } else {
      left.push(D("ready"));
    }

    // Right side: model + tokens + cost
    const right: string[] = [];
    if (this.model) right.push(D(this.model));
    if (this.tokensIn > 0 || this.tokensOut > 0) {
      right.push(D(`↑${formatTokens(this.tokensIn)} ↓${formatTokens(this.tokensOut)}`));
    }
    if (this.cost > 0) right.push(chalk.green(formatCost(this.cost)));

    const leftStr = `  ${left.join(sep)}`;
    const rightStr = right.length > 0 ? `${right.join(sep)}  ` : "";

    // Use visibleWidth to measure ANSI-aware string length
    const leftVisible = visibleWidth(leftStr);
    const rightVisible = visibleWidth(rightStr);
    const gap = Math.max(1, width - leftVisible - rightVisible);
    const line = truncateToWidth(`${leftStr}${" ".repeat(gap)}${rightStr}`, width);

    return [D("─".repeat(width)), line];
  }

  /** Bulk update from a partial state object. */
  update(data: Partial<FooterState>): void {
    if (data.project !== undefined) this.project = data.project;
    if (data.model !== undefined) this.model = data.model;
    if (data.agent !== undefined) this.agent = data.agent;
    if (data.tokensIn !== undefined) this.tokensIn = data.tokensIn;
    if (data.tokensOut !== undefined) this.tokensOut = data.tokensOut;
    if (data.cost !== undefined) this.cost = data.cost;
    if (data.startTime !== undefined) this.startTime = data.startTime;
    if (data.active !== undefined) this.active = data.active;
  }

  /** Reset usage counters (e.g. on project switch). */
  resetUsage(): void {
    this.tokensIn = 0;
    this.tokensOut = 0;
    this.cost = 0;
    this.startTime = 0;
  }
}
