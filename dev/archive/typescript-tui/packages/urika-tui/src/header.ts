import chalk from "chalk";

export function renderHeader(projectName: string, version: string): string[] {
  const B = chalk.blue;
  const D = chalk.dim;
  const BO = chalk.bold;

  const logo = [
    "██╗   ██╗██████╗ ██╗██╗  ██╗ █████╗ ",
    "██║   ██║██╔══██╗██║██║ ██╔╝██╔══██╗",
    "██║   ██║██████╔╝██║█████╔╝ ███████║",
    "██║   ██║██╔══██╗██║██╔═██╗ ██╔══██║",
    "╚██████╔╝██║  ██║██║██║  ██╗██║  ██║",
    " ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚═╝  ╚═╝",
  ];
  const logoWidth = Math.max(...logo.map((l) => l.length));

  // Box width — match the Python header
  const w = Math.max(72, logoWidth + 4);
  const barTop = "─".repeat(w - ` v${version} `.length);
  const barBot = "─".repeat(w);

  const lines: string[] = [];

  // Top border with version
  lines.push(B(`╭─ v${version} ${barTop}╮╮`));
  lines.push(B("│") + " ".repeat(w) + B("││"));

  // Logo centered in box
  for (const line of logo) {
    const totalPad = w - line.length;
    const left = Math.floor(totalPad / 2);
    const right = totalPad - left;
    lines.push(B("│") + " ".repeat(left) + B(line) + " ".repeat(right) + B("││"));
  }

  lines.push(B("│") + " ".repeat(w) + B("││"));

  // Taglines
  const t1 = "Multi-agent scientific analysis platform";
  const t1Full = `✦ ${t1}`;
  const l1 = Math.floor((w - t1Full.length) / 2);
  const r1 = w - t1Full.length - l1;
  lines.push(
    B("│") + " ".repeat(l1) + B("✦") + " " + BO(t1) + " ".repeat(r1 - 1) + B("││"),
  );

  const t2 = "Autonomous exploration · analysis · modelling · evaluation";
  const t2Full = `◆ ${t2}`;
  const l2 = Math.floor((w - t2Full.length) / 2);
  const r2 = w - t2Full.length - l2;
  lines.push(
    B("│") + " ".repeat(l2) + B("◆") + " " + D(t2) + " ".repeat(r2 - 1) + B("││"),
  );

  const t3 = `Version: ${version}`;
  const t3Full = `✦ ${t3}`;
  const l3 = Math.floor((w - t3Full.length) / 2);
  const r3 = w - t3Full.length - l3;
  lines.push(
    B("│") + " ".repeat(l3) + B("✦") + " " + D(t3) + " ".repeat(r3 - 1) + B("││"),
  );

  // Project info if present
  if (projectName && projectName !== "Urika") {
    lines.push(B("│") + " ".repeat(w) + B("││"));
    const info = `  ${projectName}`;
    const pad = " ".repeat(Math.max(0, w - info.length));
    lines.push(B("│") + chalk.white(info) + pad + B("││"));
  }

  lines.push(B("│") + " ".repeat(w) + B("││"));
  lines.push(B(`╰${barBot}╯│`));
  lines.push(` ${B(`╰${barBot}╯`)}`);
  lines.push("");

  return lines;
}
