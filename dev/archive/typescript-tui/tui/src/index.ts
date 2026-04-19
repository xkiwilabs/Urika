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
import { getApiKeyForProvider } from "./auth/login";

const VERSION = "0.1.0";

async function main() {
  const args = process.argv.slice(2);
  const headless = args.includes("--headless");
  const projectDir = args.find((a) => !a.startsWith("--"));

  const pythonCommand = process.env.PYTHON_CMD ?? "python";

  // Headless mode requires a project dir
  if (headless && !projectDir) {
    console.error("Usage: urika-tui --headless <project-dir>");
    process.exit(1);
  }

  // Load config if project dir given, otherwise use defaults
  let config;
  let resolvedDir: string | null = null;
  if (projectDir) {
    resolvedDir = resolve(projectDir);
    try {
      config = loadUrikaConfig(resolvedDir);
    } catch (err: any) {
      console.error(`Failed to load urika.toml: ${err.message}`);
      process.exit(1);
    }
  } else {
    config = {
      projectName: "",
      question: "",
      mode: "exploratory",
      defaultModel: "anthropic/claude-sonnet-4-6",
      models: {} as Record<string, string>,
      privacyMode: "open",
      localRoles: [] as string[],
    };
  }

  // Find prompts directory
  const promptsDir = findPromptsDir(resolvedDir ?? process.cwd());

  // Extract provider from default model for OAuth key resolution
  const defaultProvider = config.defaultModel.split("/")[0];

  // Create orchestrator
  const orchestrator = new Orchestrator({
    projectDir: resolvedDir ?? process.cwd(),
    promptsDir,
    defaultModel: config.defaultModel,
    modelOverrides: config.models,
    pythonCommand,
    getApiKey: () => getApiKeyForProvider(defaultProvider),
  });

  // Connect orchestrator (starts its internal RPC subprocess)
  await orchestrator.connect();

  // Initialize orchestrator with project context
  await orchestrator.initialize({
    projectName: config.projectName || "No project selected",
    question: config.question || "Use /status or tell me which project to work on",
    mode: config.mode,
    dataDir: resolvedDir ? join(resolvedDir, "data") : "",
    experimentId: "",
    currentState: resolvedDir
      ? "No experiments running. Awaiting user instructions."
      : "No project selected. Tell me which project to work on, or type /help.",
  });

  if (headless) {
    // Headless mode: read stdin, process, print JSON events via agent subscribe
    const agent = orchestrator.getAgent();
    if (agent) {
      let responseText = "";
      agent.subscribe(async (event) => {
        switch (event.type) {
          case "agent_start":
            responseText = "";
            break;
          case "message_update":
            if (event.assistantMessageEvent.type === "text_delta") {
              responseText += event.assistantMessageEvent.delta;
            }
            break;
          case "tool_execution_start":
            emit("tool_call", { tool: event.toolName, args: event.args });
            break;
          case "tool_execution_end":
            if (event.isError) {
              emit("error", { error: `Tool failed: ${event.toolName}` });
            }
            break;
          case "agent_end":
            if (responseText) {
              emit("response", { text: responseText });
            }
            break;
        }
      });
    }

    const rl = createInterface({ input: process.stdin });
    for await (const line of rl) {
      if (!line.trim()) continue;
      try {
        await orchestrator.processMessage(line.trim());
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
      projectName: config.projectName || "Urika",
      version: VERSION,
      projectDir: resolvedDir ?? process.cwd(),
      orchestrator,
      rpcClient,
    });

    // Handle clean shutdown — kill all child processes
    const cleanup = () => {
      app.stop();
      orchestrator.close();
      rpcClient.close();
    };

    process.on("SIGINT", () => { cleanup(); process.exit(0); });
    process.on("SIGTERM", () => { cleanup(); process.exit(0); });
    process.on("exit", () => { cleanup(); });
    process.on("uncaughtException", (err) => {
      cleanup();
      console.error(err);
      process.exit(1);
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
