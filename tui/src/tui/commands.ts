import type { RpcClient } from "../rpc/client";
import {
  loginProvider,
  isLoggedIn,
  getSupportedProviders,
} from "../auth/login";
import {
  removeProviderCredentials,
  listProviders,
} from "../auth/storage";

export interface SlashCommandResult {
  output: string;
  handled: boolean;
}

export interface CommandCallbacks {
  onPrompt?: (message: string) => Promise<string>;
  onOutput?: (text: string) => void;
}

export async function handleSlashCommand(
  input: string,
  rpcClient: RpcClient | null,
  projectDir: string,
  callbacks?: CommandCallbacks,
): Promise<SlashCommandResult> {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) return { output: "", handled: false };

  const [cmd, ...args] = trimmed.slice(1).split(/\s+/);
  const arg = args.join(" ");

  // Check if a project is loaded (projectDir points to a real project)
  const hasProject = projectDir !== "" && projectDir !== process.cwd();

  // Project-level commands require a loaded project
  const PROJECT_COMMANDS = ["status", "results", "config", "pause", "stop"];
  if (PROJECT_COMMANDS.includes(cmd) && !hasProject) {
    return {
      output: "  Load a project first: /project <name>",
      handled: true,
    };
  }

  switch (cmd) {
    // ── Exit ──
    case "quit":
    case "exit":
    case "q":
      return { output: "__QUIT__", handled: true };

    // ── Project management (global) ──
    case "project":
      return handleProject(arg, rpcClient, projectDir);

    case "list":
      return handleList(rpcClient);

    case "new":
      return { output: "  Use the CLI to create projects: urika new <name> -q <question>", handled: true };

    // ── Project-level commands ──
    case "config":
      return handleConfig(rpcClient, projectDir);

    case "status":
      return handleStatus(rpcClient, projectDir);

    case "results":
      return handleResults(rpcClient, projectDir);

    case "pause":
      return { output: "  Pause requested.", handled: true };

    case "stop":
      return { output: "  Stop requested.", handled: true };

    // ── Auth (global) ──
    case "login":
      return handleLogin(arg, callbacks);

    case "logout":
      return handleLogout(arg);

    case "auth":
      return handleAuthStatus();

    // ── Help ──
    case "help":
      return {
        output: [
          "",
          "  Commands:",
          "",
          "  /project <name>  Open a project",
          "  /list            List all projects",
          "  /new             Create a new project",
          "  /status          Show project/experiment status",
          "  /results         Show latest results",
          "  /config          Show configuration",
          "",
          "  /login <provider>  Login via OAuth (e.g. /login anthropic)",
          "  /logout <provider> Logout from provider",
          "  /auth              Show auth status",
          "",
          "  /pause           Pause current run",
          "  /stop            Stop current run",
          "  /quit            Exit",
          "",
          "  Everything else is sent to the orchestrator.",
          "",
        ].join("\n"),
        handled: true,
      };

    default:
      return { output: `  Unknown command: /${cmd}. Type /help for commands.`, handled: true };
  }
}

// ── Project commands ──

async function handleProject(
  name: string,
  rpcClient: RpcClient | null,
  projectDir: string,
): Promise<SlashCommandResult> {
  if (!name) {
    // No args: list all projects, highlight current
    if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
    try {
      const projects = await rpcClient.call("project.list", {}) as any[];
      if (!projects || projects.length === 0) {
        return { output: "  No projects registered. Use the CLI: urika new <name>", handled: true };
      }
      // Try to get current project name for highlighting
      let currentName = "";
      try {
        const config = await rpcClient.call("project.load_config", { project_dir: projectDir }) as any;
        currentName = config.name || "";
      } catch {
        // No current project loaded
      }
      const lines = ["", "  Projects:", ""];
      for (let i = 0; i < projects.length; i++) {
        const p = projects[i];
        const marker = p.name === currentName ? " (active)" : "";
        lines.push(`    ${i + 1}. ${p.name}${marker}`);
      }
      lines.push("", "  Type /project <number> or /project <name>", "");
      return { output: lines.join("\n"), handled: true };
    } catch (e: any) {
      return { output: `  Error: ${e.message}`, handled: true };
    }
  }

  // Switch project: accept number or name
  if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
  try {
    const projects = await rpcClient.call("project.list", {}) as any[];

    // Accept number selection (e.g. /project 1)
    const num = parseInt(name, 10);
    let match: any;
    if (!isNaN(num) && num >= 1 && num <= projects.length) {
      match = projects[num - 1];
    } else {
      match = projects.find(
        (p: any) => p.name === name || p.name.toLowerCase() === name.toLowerCase(),
      );
    }
    if (!match) {
      return {
        output: `  Project "${name}" not found. Use /list to see available projects.`,
        handled: true,
      };
    }
    return { output: `__PROJECT__:${match.path}`, handled: true };
  } catch (e: any) {
    return { output: `  Error: ${e.message}`, handled: true };
  }
}

async function handleList(rpcClient: RpcClient | null): Promise<SlashCommandResult> {
  if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
  try {
    const projects = await rpcClient.call("project.list", {}) as any[];
    if (!projects || projects.length === 0) {
      return { output: "  No projects registered.", handled: true };
    }
    const lines = ["", "  Projects:", ""];
    for (const p of projects) {
      const name = typeof p === "string" ? p : (p.name || p);
      lines.push(`    ◆ ${name}`);
    }
    lines.push("");
    return { output: lines.join("\n"), handled: true };
  } catch (e: any) {
    return { output: `  Error: ${e.message}`, handled: true };
  }
}

async function handleConfig(
  rpcClient: RpcClient | null,
  projectDir: string,
): Promise<SlashCommandResult> {
  if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
  try {
    const config = await rpcClient.call("project.load_config", { project_dir: projectDir }) as any;
    const lines = ["", "  Configuration:", ""];
    for (const [key, value] of Object.entries(config)) {
      if (typeof value === "object") continue;
      lines.push(`    ${key}: ${value}`);
    }
    lines.push("");
    return { output: lines.join("\n"), handled: true };
  } catch (e: any) {
    return { output: `  No project config loaded. Use /project <name> first.`, handled: true };
  }
}

// ── Status & results ──

async function handleStatus(
  rpcClient: RpcClient | null,
  projectDir: string,
): Promise<SlashCommandResult> {
  if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
  try {
    const config = await rpcClient.call("project.load_config", { project_dir: projectDir }) as any;
    const exps = await rpcClient.call("experiment.list", { project_dir: projectDir }) as any[];
    const lines = [
      "",
      `  Project: ${config.name || "—"}`,
      `  Question: ${config.question || "—"}`,
      `  Mode: ${config.mode || "—"}`,
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
    return { output: lines.join("\n"), handled: true };
  } catch (e: any) {
    return { output: `  Error: ${e.message}`, handled: true };
  }
}

async function handleResults(
  rpcClient: RpcClient | null,
  projectDir: string,
): Promise<SlashCommandResult> {
  if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
  try {
    const exps = await rpcClient.call("experiment.list", { project_dir: projectDir }) as any[];
    if (exps.length === 0) return { output: "  No experiments yet.", handled: true };
    const lastExp = exps[exps.length - 1];
    const progress = await rpcClient.call("progress.load", {
      project_dir: projectDir,
      experiment_id: lastExp.experiment_id,
    }) as any;
    const runs = progress.runs || [];
    if (runs.length === 0) return { output: `  ${lastExp.experiment_id}: no runs yet.`, handled: true };

    const lines = ["", `  ${lastExp.experiment_id} — ${lastExp.name || ""}`, ""];
    for (const run of runs) {
      const metrics = Object.entries(run.metrics || {})
        .map(([k, v]) => `${k}=${typeof v === "number" ? (v as number).toFixed(3) : v}`)
        .join(", ");
      lines.push(`    ${run.method}: ${metrics}`);
    }
    lines.push("");
    return { output: lines.join("\n"), handled: true };
  } catch (e: any) {
    return { output: `  Error: ${e.message}`, handled: true };
  }
}

// ── Auth commands ──

async function handleLogin(
  provider: string,
  callbacks?: CommandCallbacks,
): Promise<SlashCommandResult> {
  const providers = getSupportedProviders();

  if (!provider) {
    const list = providers
      .map((p, i) => `    ${i + 1}. ${p.id} — ${p.name}`)
      .join("\n");
    return {
      output: `\n  Login to a provider:\n\n${list}\n\n  Type /login <number> or /login <name>\n`,
      handled: true,
    };
  }

  // Accept number selection (e.g. /login 1)
  const num = parseInt(provider, 10);
  if (!isNaN(num) && num >= 1 && num <= providers.length) {
    provider = providers[num - 1].id;
  }

  if (isLoggedIn(provider)) {
    return {
      output: `  Already logged in to ${provider}. Use /logout ${provider} first.`,
      handled: true,
    };
  }

  // Show output immediately via callback (don't collect and return later)
  const out = callbacks?.onOutput ?? (() => {});

  try {
    out(`  Logging in to ${provider}...`);
    const success = await loginProvider(provider, {
      onUrl: (url, instructions) => {
        out(`  Open this URL to authenticate:\n    ${url}`);
        if (instructions) out(`  ${instructions}`);
      },
      onPrompt: async (message) => {
        if (callbacks?.onPrompt) return callbacks.onPrompt(message);
        return "";
      },
      onProgress: (msg) => out(`  ${msg}`),
    });

    if (success) {
      return { output: `  ✓ Logged in to ${provider}.`, handled: true };
    } else {
      return { output: `  Unknown provider: ${provider}. Use /login to see options.`, handled: true };
    }
  } catch (err: any) {
    return { output: `  Login failed: ${err.message}`, handled: true };
  }
}

function handleLogout(provider: string): SlashCommandResult {
  if (!provider) return { output: "  Usage: /logout <provider>", handled: true };
  if (!isLoggedIn(provider)) return { output: `  Not logged in to ${provider}.`, handled: true };
  removeProviderCredentials(provider);
  return { output: `  ✓ Logged out of ${provider}.`, handled: true };
}

function handleAuthStatus(): SlashCommandResult {
  const providers = listProviders();
  if (providers.length === 0) {
    return { output: "  No active logins. Use /login <provider> to authenticate.", handled: true };
  }
  const lines = ["", "  Authenticated providers:"];
  for (const p of providers) lines.push(`    ✓ ${p}`);
  lines.push("");
  return { output: lines.join("\n"), handled: true };
}
