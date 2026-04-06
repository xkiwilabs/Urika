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
    case "quit":
    case "exit":
    case "q":
      process.exit(0);

    case "status":
      if (!rpcClient) return { output: "Not connected to backend.", handled: true };
      try {
        const config = await rpcClient.call("project.load_config", { project_dir: projectDir });
        return { output: JSON.stringify(config, null, 2), handled: true };
      } catch (e: any) {
        return { output: `Error: ${e.message}`, handled: true };
      }

    case "results":
      if (!rpcClient) return { output: "Not connected to backend.", handled: true };
      try {
        const exps = await rpcClient.call("experiment.list", { project_dir: projectDir }) as any[];
        if (exps.length === 0) return { output: "No experiments yet.", handled: true };
        const lastExp = exps[exps.length - 1];
        const progress = await rpcClient.call("progress.load", {
          project_dir: projectDir,
          experiment_id: lastExp.experiment_id,
        });
        return { output: JSON.stringify(progress, null, 2), handled: true };
      } catch (e: any) {
        return { output: `Error: ${e.message}`, handled: true };
      }

    case "login":
      return handleLogin(arg, callbacks);

    case "logout":
      return handleLogout(arg);

    case "auth":
      return handleAuthStatus();

    case "pause":
      return { output: "Pause requested.", handled: true };

    case "stop":
      return { output: "Stop requested.", handled: true };

    case "help":
      return {
        output: [
          "/status   — Show project status",
          "/results  — Show latest experiment results",
          "/login    — Login with OAuth (e.g. /login anthropic)",
          "/logout   — Logout provider (e.g. /logout anthropic)",
          "/auth     — Show authentication status",
          "/pause    — Pause current run",
          "/stop     — Stop current run",
          "/quit     — Exit Urika TUI",
          "/help     — Show this help",
          "",
          "Everything else is sent to the orchestrator as natural language.",
        ].join("\n"),
        handled: true,
      };

    default:
      return { output: `Unknown command: /${cmd}. Type /help for available commands.`, handled: true };
  }
}

async function handleLogin(
  provider: string,
  callbacks?: CommandCallbacks,
): Promise<SlashCommandResult> {
  if (!provider) {
    const providers = getSupportedProviders();
    const list = providers.map((p) => `  ${p.id} — ${p.name}`).join("\n");
    return {
      output: `Usage: /login <provider>\n\nAvailable providers:\n${list}`,
      handled: true,
    };
  }

  if (isLoggedIn(provider)) {
    return {
      output: `Already logged in to ${provider}. Use /logout ${provider} first to re-authenticate.`,
      handled: true,
    };
  }

  try {
    const messages: string[] = [];
    const success = await loginProvider(provider, {
      onUrl: (url, instructions) => {
        messages.push(`Open this URL to authenticate:\n  ${url}`);
        if (instructions) messages.push(instructions);
      },
      onPrompt: async (message) => {
        if (callbacks?.onPrompt) {
          return callbacks.onPrompt(message);
        }
        // Fallback: no interactive prompt available
        return "";
      },
      onProgress: (msg) => {
        messages.push(msg);
      },
    });

    if (success) {
      messages.push(`Logged in to ${provider}.`);
    } else {
      messages.push(`Unknown provider: ${provider}. Use /login to see available providers.`);
    }

    return { output: messages.join("\n"), handled: true };
  } catch (err: any) {
    return { output: `Login failed: ${err.message}`, handled: true };
  }
}

function handleLogout(provider: string): SlashCommandResult {
  if (!provider) {
    return { output: "Usage: /logout <provider>", handled: true };
  }

  if (!isLoggedIn(provider)) {
    return { output: `Not logged in to ${provider}.`, handled: true };
  }

  removeProviderCredentials(provider);
  return { output: `Logged out of ${provider}.`, handled: true };
}

function handleAuthStatus(): SlashCommandResult {
  const providers = listProviders();
  if (providers.length === 0) {
    return { output: "No active logins. Use /login <provider> to authenticate.", handled: true };
  }

  const lines = ["Authenticated providers:"];
  for (const p of providers) {
    lines.push(`  ${p}`);
  }
  return { output: lines.join("\n"), handled: true };
}
