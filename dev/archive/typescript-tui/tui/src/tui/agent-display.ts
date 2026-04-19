import chalk from "chalk";

const AGENT_COLORS: Record<string, (s: string) => string> = {
  planning_agent: chalk.cyan,
  task_agent: chalk.green,
  evaluator: chalk.yellow,
  advisor: chalk.magenta,
  tool_builder: chalk.hex("#FF8C00"),
  literature_agent: chalk.blueBright,
  report_agent: chalk.white,
  presentation_agent: chalk.greenBright,
  data_agent: chalk.cyanBright,
  finalizer: chalk.magentaBright,
  orchestrator: chalk.bold.white,
};

export function formatAgentLabel(role: string): string {
  const colorFn = AGENT_COLORS[role] ?? chalk.white;
  const displayName = role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return colorFn(`▸ ${displayName}`);
}

export function getAgentColor(role: string): (s: string) => string {
  return AGENT_COLORS[role] ?? chalk.white;
}
