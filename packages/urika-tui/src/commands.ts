import { CMD_PROJECT_PREFIX, type CommandHandler } from "@urika/agent-runtime";

/**
 * Urika-specific command handlers for slash commands that need
 * custom logic beyond what the declarative config can express.
 *
 * Each handler receives the argument string (everything after the command name)
 * and a CommandContext with RPC access and project state.
 */
export const commandHandlers: Record<string, CommandHandler> = {
  project: async (args, ctx) => {
    if (!args) {
      // No args: list all projects with numbers
      const projects = (await ctx.rpc.call("project.list", {})) as any[];
      if (!projects.length) return "  No projects. Use: urika new <name>";

      const lines = ["", "  Projects:", ""];
      for (let i = 0; i < projects.length; i++) {
        lines.push(`    ${i + 1}. ${projects[i].name}`);
      }
      lines.push("", "  Type /project <number> or /project <name>", "");
      return lines.join("\n");
    }

    // Switch project: accept number or name
    const projects = (await ctx.rpc.call("project.list", {})) as any[];
    const num = parseInt(args, 10);
    let match: any;
    if (!isNaN(num) && num >= 1 && num <= projects.length) {
      match = projects[num - 1];
    } else {
      match = projects.find(
        (p: any) => p.name.toLowerCase() === args.toLowerCase(),
      );
    }
    if (!match) return `  Project not found: ${args}`;
    await ctx.switchProject(match.path);
    return CMD_PROJECT_PREFIX + match.path;
  },

  new: async () => {
    return "  Use the CLI: urika new <name> -q <question>";
  },

  status: async (_args, ctx) => {
    const config = (await ctx.rpc.call("project.load_config", {
      project_dir: ctx.projectDir,
    })) as any;
    const exps = (await ctx.rpc.call("experiment.list", {
      project_dir: ctx.projectDir,
    })) as any[];

    const lines = [
      "",
      `  Project: ${config.name ?? "—"}`,
      `  Question: ${config.question ?? "—"}`,
      `  Mode: ${config.mode ?? "—"}`,
      `  Experiments: ${exps.length}`,
      "",
    ];

    if (exps.length > 0) {
      lines.push("  Recent experiments:");
      for (const exp of exps.slice(-5)) {
        lines.push(`    ${exp.experiment_id}  ${exp.name || "—"}`);
      }
      lines.push("");
    }

    return lines.join("\n");
  },

  results: async (_args, ctx) => {
    const exps = (await ctx.rpc.call("experiment.list", {
      project_dir: ctx.projectDir,
    })) as any[];
    if (!exps.length) return "  No experiments.";

    const last = exps[exps.length - 1];
    const progress = (await ctx.rpc.call("progress.load", {
      project_dir: ctx.projectDir,
      experiment_id: last.experiment_id,
    })) as any;
    const runs = progress.runs ?? [];
    if (!runs.length) return `  ${last.experiment_id}: no runs.`;

    const lines = ["", `  ${last.experiment_id} — ${last.name || ""}`, ""];
    for (const r of runs) {
      const metrics = Object.entries(r.metrics ?? {})
        .map(
          ([k, v]) =>
            `${k}=${typeof v === "number" ? (v as number).toFixed(3) : v}`,
        )
        .join(", ");
      lines.push(`    ${r.method}: ${metrics}`);
    }
    lines.push("");
    return lines.join("\n");
  },

  list: async (_args, ctx) => {
    const projects = (await ctx.rpc.call("project.list", {})) as any[];
    if (!projects.length) return "  No projects.";
    return projects.map((p: any, i: number) => `  ${i + 1}. ${p.name}`).join("\n");
  },

  pause: async () => "  Pause requested.",

  stop: async () => "  Stop requested.",

  config: async (_args, ctx) => {
    const config = (await ctx.rpc.call("project.load_config", {
      project_dir: ctx.projectDir,
    })) as any;

    const lines = ["", "  Configuration:", ""];
    for (const [key, value] of Object.entries(config)) {
      if (typeof value === "object") continue;
      lines.push(`    ${key}: ${value}`);
    }
    lines.push("");
    return lines.join("\n");
  },
};
