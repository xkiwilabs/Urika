import chalk from "chalk";

export function renderHeader(projectName: string, version: string): string[] {
  const logo = [
    chalk.cyan("  _   _      _ _         "),
    chalk.cyan(" | | | |_ __(_) | ____ _ "),
    chalk.cyan(" | | | | '__| | |/ / _` |"),
    chalk.cyan(" | |_| | |  | |   < (_| |"),
    chalk.cyan("  \\___/|_|  |_|_|\\_\\__,_|"),
  ];
  const info = projectName
    ? `  ${chalk.dim("v" + version)}  ${chalk.white(projectName)}`
    : `  ${chalk.dim("v" + version)}`;
  return [...logo, info, ""];
}
