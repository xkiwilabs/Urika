import chalk from "chalk";
import type { Component } from "@mariozechner/pi-tui";
import { truncateToWidth } from "@mariozechner/pi-tui";

export interface StatusBarState {
  project: string;
  experimentId: string;
  turn: number;
  agent: string;
  model: string;
  tokens: number;
  cost: number;
  elapsed: number;
}

export class StatusBar implements Component {
  private state: StatusBarState = {
    project: "",
    experimentId: "",
    turn: 0,
    agent: "",
    model: "",
    tokens: 0,
    cost: 0,
    elapsed: 0,
  };

  update(partial: Partial<StatusBarState>): void {
    Object.assign(this.state, partial);
  }

  invalidate(): void {}

  render(width: number): string[] {
    const s = this.state;
    const sep = chalk.dim(" │ ");
    const parts: string[] = [];

    if (s.experimentId) parts.push(chalk.cyan(s.experimentId));
    if (s.turn > 0) parts.push(chalk.white(`turn ${s.turn}`));
    if (s.agent) parts.push(chalk.yellow(s.agent));
    if (s.model) parts.push(chalk.dim(s.model));
    if (s.cost > 0) parts.push(chalk.green(`$${s.cost.toFixed(2)}`));
    if (s.elapsed > 0) parts.push(chalk.dim(`${Math.floor(s.elapsed / 1000)}s`));

    const line = parts.length > 0
      ? parts.join(sep)
      : chalk.dim("Ready");

    const divider = chalk.dim("─".repeat(width));
    return [divider, truncateToWidth(line, width)];
  }
}
