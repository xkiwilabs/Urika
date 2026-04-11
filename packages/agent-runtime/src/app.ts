import chalk from "chalk";
import { loadSystemConfig } from "./config/loader";
import { RpcClient } from "./rpc/client";
import { createRuntime, type RuntimeFactoryOptions } from "./runtime/factory";
import { GenericOrchestrator, type OrchestratorContext } from "./orchestrator/orchestrator";
import { AgentTuiApp, CMD_QUIT, CMD_PROJECT_PREFIX } from "./tui/app";
import type { CommandContext as TuiCommandContext, SubscriptionHandlers } from "./tui/app";
import type { RuntimeEvent } from "./runtime/types";

// ── Public types ──

export interface CommandContext {
  rpc: RpcClient;
  projectDir: string;
  projectName: string;
  switchProject: (path: string) => Promise<void>;
  /** Access to the orchestrator for session management. */
  orchestrator: GenericOrchestrator;
  /** Write directly to the chat area (for multi-message output). */
  addChat: (text: string) => void;
}

export type CommandHandler = (args: string, ctx: CommandContext) => Promise<string>;

export interface AppContext {
  projectDir: string;
  projectName: string;
  projectConfig?: any;
  rpc: RpcClient;
}

export interface AppOptions {
  /** Path to runtime.toml configuration file. */
  configPath: string;

  /** Custom header renderer. Returns lines of text for the TUI header. */
  renderHeader?: (projectName: string, version: string) => string[];

  /** Custom slash-command handlers keyed by command name (without /). */
  commandHandlers?: Record<string, CommandHandler>;

  /** Supply extra prompt template variables at runtime. */
  getPromptVariables?: (ctx: AppContext) => Promise<Record<string, string>>;

  /**
   * Called when a project switch occurs (via the switch_project tool).
   * Should return the resolved project name and directory.
   */
  onProjectSwitch?: (
    projectDir: string,
    ctx: AppContext,
  ) => Promise<{ projectName: string; projectDir: string }>;

  /** Runtime factory options (API key resolver, claude path, etc.). */
  runtimeOptions?: RuntimeFactoryOptions;
}

export interface App {
  start(): void;
  stop(): void;
}

// ── Default header ──

function defaultHeader(projectName: string, version: string): string[] {
  const name = projectName || "No project";
  return [
    chalk.cyan.bold(`Agent Runtime v${version}`),
    chalk.dim(`Project: ${name}`),
    "",
  ];
}

// ── createApp ──

/**
 * Create a fully wired agent application.
 *
 * This is the main public API of @urika/agent-runtime. It:
 * 1. Loads runtime.toml configuration
 * 2. Spawns the RPC server subprocess
 * 3. Creates the runtime backend (Claude, Pi, Codex, Google)
 * 4. Creates the generic orchestrator with config-driven tools
 * 5. Builds the TUI with streaming event subscription
 *
 * Returns an App object with start() and stop().
 */
export async function createApp(options: AppOptions): Promise<App> {
  // 1. Load config
  const config = loadSystemConfig(options.configPath);

  // 2. Spawn RPC server
  const rpcParts = config.system.rpcCommand.split(" ");
  const rpcClient = new RpcClient(rpcParts[0], rpcParts.slice(1));

  // 3. Create runtime
  const runtime = createRuntime(
    config.runtime.defaultBackend,
    options.runtimeOptions,
  );

  // 4. Create orchestrator
  const orchestrator = new GenericOrchestrator(runtime, rpcClient, config);

  // Mutable state
  let projectName = "";
  let projectDir = "";

  // Wire project switch
  orchestrator.onProjectSwitch = async (path: string) => {
    if (options.onProjectSwitch) {
      const result = await options.onProjectSwitch(path, {
        projectDir,
        projectName,
        rpc: rpcClient,
      });
      projectName = result.projectName;
      projectDir = result.projectDir;
      return {
        projectName: result.projectName,
        projectDir: result.projectDir,
      };
    }
    // Default: treat path as project dir, derive name from last segment
    projectDir = path;
    projectName = path.split("/").pop() || "project";
    return { projectName, projectDir };
  };

  // 5. Build prompt variables
  const promptVars = options.getPromptVariables
    ? await options.getPromptVariables({
        projectDir,
        projectName,
        rpc: rpcClient,
      })
    : {};

  // 6. Initialize orchestrator (no project)
  await orchestrator.initialize({
    projectName: "",
    question: "",
    mode: "exploratory",
    dataDir: "",
    experimentId: "",
    currentState: "No project selected.",
    promptVariables: promptVars,
  });

  // 7. Build command handlers that bridge the TUI CommandContext to our CommandContext
  const tuiCommandHandlers: Record<
    string,
    (args: string, ctx: TuiCommandContext) => Promise<string>
  > = {};

  if (options.commandHandlers) {
    for (const [name, handler] of Object.entries(options.commandHandlers)) {
      tuiCommandHandlers[name] = async (
        args: string,
        tuiCtx: TuiCommandContext,
      ): Promise<string> => {
        const cmdCtx: CommandContext = {
          rpc: rpcClient,
          projectDir,
          projectName,
          orchestrator,
          addChat: tuiCtx.addChat,
          switchProject: async (path: string) => {
            const result = orchestrator.onProjectSwitch
              ? await orchestrator.onProjectSwitch(path)
              : { projectName: path.split("/").pop() || "project", projectDir: path };
            projectName = result.projectName;
            projectDir = result.projectDir;

            // Tell the Python orchestrator about the project switch
            await rpcClient.call("orchestrator.set_project", {
              project_dir: projectDir,
            });
          },
        };
        return handler(args, cmdCtx);
      };
    }
  }

  // 8. Create TUI
  const tuiApp = new AgentTuiApp({
    projectName: "",
    version: config.system.version,
    projectDir: "",
    renderHeader: options.renderHeader ?? defaultHeader,
    commands: config.commands,
    commandHandlers: tuiCommandHandlers,
    rpcClient,
    onSetupSubscription: (handlers: SubscriptionHandlers) => {
      let streamingMarkdown: import("@mariozechner/pi-tui").Markdown | null = null;
      let streamingText = "";
      let totalTokensIn = 0;
      let totalTokensOut = 0;
      let totalCost = 0;
      let lastModel = "";

      // Wire RPC notifications (from long-running tools like run_experiment)
      // to update the loader + footer + chat stream in real-time.
      const unsubRpc = rpcClient.onNotification((method, params) => {
        if (method === "experiment.progress") {
          const event = String(params.event ?? "");
          const detail = String(params.detail ?? "");

          // Update loader and footer based on progress event type
          if (event === "agent") {
            // Subagent started — update loader with agent name
            const agentName = detail.split("—")[0]?.trim() || detail;
            handlers.showLoader(agentName);
            handlers.updateFooter({ agent: agentName });
          } else if (event === "turn") {
            // Turn started — show in footer
            handlers.updateFooter({ agent: detail });
          } else if (event === "phase") {
            // Phase change — update loader
            handlers.showLoader(detail);
          } else if (event === "result") {
            // Result — show in chat
            handlers.addChat(chalk.dim(`  ${detail}`));
          }
          handlers.requestRender();
        } else if (method === "experiment.message") {
          const text = String(params.text ?? "");
          if (text) {
            handlers.addChat(text);
            handlers.requestRender();
          }
        } else if (method === "agent.started") {
          const agent = String(params.agent ?? "");
          handlers.showLoader(agent.replace(/_/g, " "));
          handlers.updateFooter({ agent });
          handlers.requestRender();
        } else if (method === "agent.message") {
          const text = String(params.text ?? "");
          if (text) {
            handlers.addChat(text);
            handlers.requestRender();
          }
        } else if (method === "agent.completed") {
          handlers.hideLoader();
          handlers.updateFooter({ agent: "" });
          const tokensIn = Number(params.tokens_in ?? 0);
          const tokensOut = Number(params.tokens_out ?? 0);
          const cost = Number(params.cost_usd ?? 0);
          totalTokensIn += tokensIn;
          totalTokensOut += tokensOut;
          totalCost += cost;
          handlers.updateFooter({ tokensIn: totalTokensIn, tokensOut: totalTokensOut, cost: totalCost });
          handlers.requestRender();

        // Orchestrator chat notifications
        } else if (method === "orchestrator.thinking") {
          handlers.showLoader("Thinking...");
          handlers.updateFooter({ active: true, startTime: Date.now() });
          handlers.requestRender();
        } else if (method === "orchestrator.delta") {
          const text = String(params.text ?? "");
          if (text) {
            if (!streamingMarkdown) {
              streamingMarkdown = handlers.addMarkdown("");
              handlers.hideLoader();
            }
            streamingText += text;
            streamingMarkdown.setText(streamingText);
            handlers.requestRender();
          }
        } else if (method === "orchestrator.done") {
          streamingMarkdown = null;
          streamingText = "";
          handlers.hideLoader();
          const tokensIn = Number(params.tokens_in ?? 0);
          const tokensOut = Number(params.tokens_out ?? 0);
          const cost = Number(params.cost_usd ?? 0);
          totalTokensIn += tokensIn;
          totalTokensOut += tokensOut;
          totalCost += cost;
          lastModel = String(params.model ?? lastModel);
          handlers.updateFooter({
            active: false,
            agent: "",
            tokensIn: totalTokensIn,
            tokensOut: totalTokensOut,
            cost: totalCost,
            model: lastModel,
          });
          handlers.requestRender();
        }
      });

      // Return unsubscribe for RPC notifications
      return () => {
        unsubRpc();
      };
    },
    onMessage: async (text: string) => {
      // Send to Python orchestrator via RPC — ALL LLM calls go through Python
      const result = await rpcClient.call("orchestrator.chat", {
        message: text,
      }) as any;
      // Response is already streamed via notifications — but if not,
      // show the final result
      if (result?.response && !result.response.startsWith("Error:")) {
        // Response was already shown via orchestrator.delta notifications
        // Only show here if notifications didn't fire
      }
    },
    onSteer: (_text: string) => {
      // Steering not supported with RPC orchestrator (single-threaded)
      // The message will be processed on the next turn
    },
    onAbort: () => {
      // Can't abort a blocking RPC call — user should use /stop
    },
  });

  return {
    start: () => tuiApp.start(),
    stop: () => {
      tuiApp.stop();
      orchestrator.close();
      rpcClient.close();
    },
  };
}
