/**
 * Urika TUI — Terminal UI + Adaptive Orchestrator
 *
 * Two modes:
 *   --interactive (default): pi-tui with conversational orchestrator
 *   --headless: stdout JSON events, no TUI
 */

import { resolve, join } from "path";
import { loadUrikaConfig } from "./config/loader";
import { Orchestrator } from "./orchestrator/orchestrator";
import { UrikaApp } from "./tui/app";
import { RpcClient } from "./rpc/client";
import { createInterface } from "readline";
import { readdirSync } from "fs";

const VERSION = "0.1.0";

async function main() {
  const args = process.argv.slice(2);
  const headless = args.includes("--headless");
  const projectDir = args.find((a) => !a.startsWith("--"));

  if (!projectDir) {
    console.error("Usage: urika-tui [--headless] <project-dir>");
    process.exit(1);
  }

  const resolvedDir = resolve(projectDir);

  // Load config
  let config;
  try {
    config = loadUrikaConfig(resolvedDir);
  } catch (err: any) {
    console.error(`Failed to load urika.toml: ${err.message}`);
    process.exit(1);
  }

  // Find prompts directory
  const promptsDir = findPromptsDir(resolvedDir);
  const pythonCommand = process.env.PYTHON_CMD ?? "python";

  // Create orchestrator
  const orchestrator = new Orchestrator({
    projectDir: resolvedDir,
    promptsDir,
    defaultModel: config.defaultModel,
    modelOverrides: config.models,
    pythonCommand,
  });

  // Connect orchestrator (starts its internal RPC subprocess)
  await orchestrator.connect();

  // Initialize orchestrator with project context
  await orchestrator.initialize({
    projectName: config.projectName,
    question: config.question,
    mode: config.mode,
    dataDir: join(resolvedDir, "data"),
    experimentId: "",
    currentState: "No experiments running. Awaiting user instructions.",
  });

  if (headless) {
    // Headless mode: read stdin, process, print JSON events
    orchestrator.setEvents({
      onAgentStart: (name) => emit("agent_start", { agent: name }),
      onAgentOutput: (name, text) =>
        emit("agent_output", { agent: name, text }),
      onAgentEnd: (name) => emit("agent_end", { agent: name }),
      onText: (text) => emit("text", { text }),
      onToolCall: (name, args) => emit("tool_call", { tool: name, args }),
      onError: (error) => emit("error", { error }),
    });

    const rl = createInterface({ input: process.stdin });
    for await (const line of rl) {
      if (!line.trim()) continue;
      try {
        const response = await orchestrator.processMessage(line.trim());
        emit("response", { text: response });
      } catch (err: any) {
        emit("error", { error: err.message });
      }
    }

    orchestrator.close();
  } else {
    // Interactive mode: create a separate RPC client for slash commands
    const rpcClient = new RpcClient(pythonCommand, ["-m", "urika.rpc"]);

    // Launch TUI
    const app = new UrikaApp({
      projectName: config.projectName,
      version: VERSION,
      projectDir: resolvedDir,
      orchestrator,
      rpcClient,
    });

    // Handle clean shutdown
    process.on("SIGINT", () => {
      app.stop();
      orchestrator.close();
      rpcClient.close();
      process.exit(0);
    });

    app.start();
  }
}

function emit(event: string, data: Record<string, unknown>): void {
  console.log(JSON.stringify({ event, ...data }));
}

/**
 * Find the prompts directory. Tries several locations:
 * 1. Relative to project dir (dev layout)
 * 2. Via URIKA_PROMPTS_DIR env var
 * 3. Relative to this compiled file
 */
function findPromptsDir(projectDir: string): string {
  const candidates = [
    // Dev: running from repo root
    resolve(projectDir, "..", "src", "urika", "agents", "roles", "prompts"),
    resolve(
      projectDir,
      "..",
      "..",
      "src",
      "urika",
      "agents",
      "roles",
      "prompts",
    ),
    // Env override
    process.env.URIKA_PROMPTS_DIR,
    // Fallback: look relative to this file
    resolve(
      __dirname,
      "..",
      "..",
      "src",
      "urika",
      "agents",
      "roles",
      "prompts",
    ),
  ].filter(Boolean) as string[];

  for (const dir of candidates) {
    try {
      const files = readdirSync(dir);
      if (files.some((f: string) => f.endsWith("_system.md"))) {
        return dir;
      }
    } catch {
      // Directory doesn't exist — try next candidate
    }
  }

  // Last resort — return a reasonable default and let prompt loading fail gracefully
  return resolve(projectDir, "prompts");
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
