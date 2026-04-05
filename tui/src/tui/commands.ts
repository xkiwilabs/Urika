import type { RpcClient } from "../rpc/client";

export interface SlashCommandResult {
  output: string;
  handled: boolean;
}

export async function handleSlashCommand(
  input: string,
  rpcClient: RpcClient | null,
  projectDir: string,
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

    case "pause":
      return { output: "Pause requested.", handled: true };

    case "stop":
      return { output: "Stop requested.", handled: true };

    case "help":
      return {
        output: [
          "/status   — Show project status",
          "/results  — Show latest experiment results",
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
