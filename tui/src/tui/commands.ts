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

  switch (cmd) {
    // ── Exit ──
    case "quit":
    case "exit":
    case "q":
      return { output: "__QUIT__", handled: true };

    // ── Project management ──
    case "project":
      return handleProject(arg, rpcClient, projectDir);

    case "list":
      return handleList(rpcClient);

    case "new":
      return { output: "Use the CLI to create projects: urika new <name> -q <question>", handled: true };

    case "config":
      return handleConfig(rpcClient, projectDir);

    // ── Status & results ──
    case "status":
      return handleStatus(rpcClient, projectDir);

    case "results":
      return handleResults(rpcClient, projectDir);

    // ── Auth ──
    case "login":
      return handleLogin(arg, callbacks);

    case "logout":
      return handleLogout(arg);

    case "auth":
      return handleAuthStatus();

    // ── Run control ──
    case "pause":
      return { output: "Pause requested.", handled: true };

    case "stop":
      return { output: "Stop requested.", handled: true };

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
    // Show current project
    if (!rpcClient) return { output: "  Not connected to backend.", handled: true };
    try {
      const config = await rpcClient.call("project.load_config", { project_dir: projectDir }) as any;
      return {
        output: [
          "",
          `  Project: ${config.name || "none"}`,
          `  Question: ${config.question || "—"}`,
          `  Mode: ${config.mode || "—"}`,
          "",
          "  Usage: /project <name> to switch projects",
          "",
        ].join("\n"),
        handled: true,
      };
    } catch {
      return { output: "  No project loaded. Usage: /project <name>", handled: true };
    }
  }

  // TODO: Switch project — needs to update orchestrator context
  return {
    output: `  Project switching not yet wired. Use: urika tui <project-dir>`,
    handled: true,
  };
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
  if (!provider) {
    const providers = getSupportedProviders();
    const list = providers.map((p) => `    ${p.id} — ${p.name}`).join("\n");
    return {
      output: `\n  Usage: /login <provider>\n\n  Available providers:\n${list}\n`,
      handled: true,
    };
  }

  if (isLoggedIn(provider)) {
    return {
      output: `  Already logged in to ${provider}. Use /logout ${provider} first.`,
      handled: true,
    };
  }

  try {
    const messages: string[] = [];
    const success = await loginProvider(provider, {
      onUrl: (url, instructions) => {
        messages.push(`  Open this URL to authenticate:\n    ${url}`);
        if (instructions) messages.push(`  ${instructions}`);
      },
      onPrompt: async (message) => {
        if (callbacks?.onPrompt) return callbacks.onPrompt(message);
        return "";
      },
      onProgress: (msg) => messages.push(`  ${msg}`),
    });

    if (success) {
      messages.push(`  ✓ Logged in to ${provider}.`);
    } else {
      messages.push(`  Unknown provider: ${provider}. Use /login to see options.`);
    }
    return { output: messages.join("\n"), handled: true };
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
