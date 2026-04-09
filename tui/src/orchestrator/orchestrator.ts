import { Agent } from "@mariozechner/pi-agent-core";
import type {
  AgentTool as PiAgentTool,
  AgentEvent,
  AgentToolResult,
  AgentMessage,
} from "@mariozechner/pi-agent-core";
import { getModel, Type, streamSimple } from "@mariozechner/pi-ai";
import type {
  Model,
  Message,
  TextContent,
} from "@mariozechner/pi-ai";
import {
  buildOrchestratorPrompt,
  type OrchestratorContext,
} from "./system-prompt";
import { buildAgentTools, type AgentTool } from "./agent-tools";
import { RpcClient } from "../rpc/client";

export interface OrchestratorConfig {
  projectDir: string;
  promptsDir: string;
  defaultModel: string;
  modelOverrides: Record<string, string>;
  pythonCommand: string;
  /** Optional function that resolves an API key before each LLM call. */
  getApiKey?: () => Promise<string | null>;
}

/** Global tools — available without a project. */
const GLOBAL_TOOLS = ["list_projects", "switch_project"] as const;

/** Project-level tools — only available after loading a project. */
const PROJECT_TOOLS = [
  "list_experiments",
  "create_experiment",
  "append_run",
  "load_progress",
  "get_best_run",
  "load_criteria",
  "load_methods",
  "finalize_project",
  "profile_data",
  "search_knowledge",
  "list_knowledge",
  "list_tools",
  "update_criteria",
  "start_session",
  "pause_session",
  "generate_report",
  "summarize_project",
] as const;

/** Maps orchestrator tool names to Python RPC method paths. */
const RPC_METHOD_MAP: Record<string, string> = {
  list_projects: "project.list",
  switch_project: "project.list", // uses list to find project path, then switches
  list_experiments: "experiment.list",
  create_experiment: "experiment.create",
  append_run: "progress.append_run",
  load_progress: "progress.load",
  get_best_run: "progress.get_best_run",
  load_criteria: "criteria.load",
  load_methods: "methods.list",
  finalize_project: "finalize.run",
  profile_data: "data.profile",
  search_knowledge: "knowledge.search",
  list_knowledge: "knowledge.list",
  list_tools: "tools.list",
  update_criteria: "criteria.append",
  start_session: "session.start",
  pause_session: "session.pause",
  generate_report: "report.results_summary",
  summarize_project: "project.summarize",
};

export class Orchestrator {
  private config: OrchestratorConfig;
  private agentTools: AgentTool[];
  private rpcClient: RpcClient | null = null;
  private agent: Agent | null = null;
  private systemPrompt: string = "";
  private hasProject = false;

  /** Callback for project switch notifications to the TUI. */
  onProjectSwitch?: (info: {
    projectName: string;
    question: string;
    mode: string;
    projectDir: string;
  }) => void;

  constructor(config: OrchestratorConfig) {
    this.config = config;
    this.agentTools = buildAgentTools({
      promptsDir: config.promptsDir,
      projectDir: config.projectDir,
      experimentId: "",
      defaultModel: config.defaultModel,
      modelOverrides: config.modelOverrides,
    });
  }

  /** Returns the names of all tools available to the orchestrator LLM. */
  getToolNames(): string[] {
    if (!this.hasProject) {
      return [...GLOBAL_TOOLS];
    }
    return [
      ...this.agentTools.map((t) => t.name),
      ...PROJECT_TOOLS,
    ];
  }

  /**
   * Subscribe to agent events for UI updates.
   * Returns an unsubscribe function.
   */
  subscribe(
    listener: (event: AgentEvent, signal: AbortSignal) => Promise<void> | void,
  ): () => void {
    if (!this.agent) {
      // Queue subscription until agent is created
      throw new Error("Cannot subscribe before connect() and initialize()");
    }
    return this.agent.subscribe(listener);
  }

  /** Start the Python RPC server subprocess. */
  async connect(): Promise<void> {
    this.rpcClient = new RpcClient(this.config.pythonCommand, [
      "-m",
      "urika.rpc",
    ]);
  }

  /**
   * Initialize the orchestrator with project context.
   * Creates (or recreates) the pi-agent-core Agent with appropriate tools.
   * Call after connect() and before processMessage().
   */
  async initialize(projectContext: {
    projectName: string;
    question: string;
    mode: string;
    dataDir: string;
    experimentId: string;
    currentState: string;
  }): Promise<void> {
    this.hasProject = projectContext.projectName !== "" &&
      projectContext.projectName !== "No project selected";

    // Update projectDir from dataDir (dataDir is always projectDir + "/data")
    if (projectContext.dataDir) {
      const newProjectDir = projectContext.dataDir.replace(/\/data\/?$/, "");
      if (newProjectDir) {
        this.config.projectDir = newProjectDir;
      }
    }

    this.systemPrompt = buildOrchestratorPrompt({
      promptsDir: this.config.promptsDir,
      ...projectContext,
    });

    const orchestratorModel =
      this.config.modelOverrides["orchestrator"] ?? this.config.defaultModel;
    const piTools = this.buildPiAgentTools();

    // Preserve existing subscriptions when recreating the agent
    const previousAgent = this.agent;

    this.agent = new Agent({
      initialState: {
        systemPrompt: this.systemPrompt,
        model: this.resolveModel(orchestratorModel),
        tools: piTools,
        thinkingLevel: "off",
      },
      convertToLlm: (messages: AgentMessage[]) => {
        // Pass through standard LLM messages, filter custom types
        return messages.filter(
          (m): m is Message =>
            typeof m === "object" &&
            m !== null &&
            "role" in m &&
            (m.role === "user" || m.role === "assistant" || m.role === "toolResult"),
        );
      },
      getApiKey: async (provider: string) => {
        if (!this.config.getApiKey) return undefined;
        const key = await this.config.getApiKey();
        return key ?? undefined;
      },
      streamFn: streamSimple,
    });

    // If the previous agent had subscribers, they would need to re-subscribe.
    // The TUI re-subscribes via setupSubscription() after initialize().
  }

  /**
   * Process a user message through the orchestrator.
   * The Agent handles the entire loop: LLM -> tool calls -> execute -> LLM -> ... -> done
   */
  async processMessage(userMessage: string): Promise<void> {
    if (!this.agent) {
      throw new Error("Orchestrator not initialized — call connect() then initialize()");
    }
    await this.agent.prompt(userMessage);
  }

  /**
   * Inject a user message mid-run (steering).
   * The agent will see this after the current assistant turn finishes.
   */
  steer(message: string): void {
    if (!this.agent) return;
    this.agent.steer({
      role: "user" as const,
      content: message,
      timestamp: Date.now(),
    });
  }

  /** Abort the current agent run. */
  abort(): void {
    this.agent?.abort();
  }

  /** Get the underlying Agent for direct subscription. */
  getAgent(): Agent | null {
    return this.agent;
  }

  /** Shut down the RPC subprocess. */
  close(): void {
    this.agent?.abort();
    this.rpcClient?.close();
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  /** Parse a "provider/model-id" string and return a pi-ai Model. */
  private resolveModel(modelString: string): Model<any> {
    const [provider, ...modelParts] = modelString.split("/");
    const modelId = modelParts.join("/");
    try {
      return getModel(provider as any, modelId as any);
    } catch {
      throw new Error(
        `Model not found: ${modelString}. Check your urika.toml [runtime] config.`,
      );
    }
  }

  /** Run an agent sub-agent via a separate pi-agent-core Agent. */
  private async executeAgentSubagent(
    agentDef: AgentTool,
    instructions: string,
    signal?: AbortSignal,
  ): Promise<AgentToolResult<{ role: string }>> {
    const model = this.resolveModel(agentDef.model);
    const apiKey = this.config.getApiKey
      ? (await this.config.getApiKey()) ?? undefined
      : undefined;

    const subAgent = new Agent({
      initialState: {
        systemPrompt: agentDef.systemPrompt,
        model,
        tools: [],
        thinkingLevel: "off",
      },
      convertToLlm: (messages: AgentMessage[]) =>
        messages.filter(
          (m): m is Message =>
            typeof m === "object" &&
            m !== null &&
            "role" in m &&
            (m.role === "user" || m.role === "assistant" || m.role === "toolResult"),
        ),
      getApiKey: async () => apiKey,
      streamFn: streamSimple,
    });

    // Run the sub-agent with the instructions
    await subAgent.prompt(instructions);

    // Extract text from the final messages
    const finalMessages = subAgent.state.messages;
    const textParts: string[] = [];
    for (const msg of finalMessages) {
      if (
        typeof msg === "object" &&
        msg !== null &&
        "role" in msg &&
        (msg as any).role === "assistant"
      ) {
        const content = (msg as any).content;
        if (Array.isArray(content)) {
          for (const c of content) {
            if (c.type === "text") textParts.push(c.text);
          }
        }
      }
    }

    return {
      content: [{ type: "text", text: textParts.join("\n") || "No output from agent." }],
      details: { role: agentDef.name },
    };
  }

  /** Call the Python RPC server for state operations. */
  private async executeRpcTool(
    name: string,
    args: Record<string, any>,
  ): Promise<AgentToolResult<{ rpcMethod: string }>> {
    if (!this.rpcClient) {
      throw new Error("RPC client not connected — call connect() first");
    }

    // Special handling for switch_project
    if (name === "switch_project") {
      return this.handleSwitchProject(args.name);
    }

    const rpcMethod = RPC_METHOD_MAP[name];
    if (!rpcMethod) {
      throw new Error(`Unknown tool: ${name}`);
    }

    const params = { ...args, project_dir: this.config.projectDir };
    const result = await this.rpcClient.call(rpcMethod, params);
    return {
      content: [{ type: "text", text: JSON.stringify(result) }],
      details: { rpcMethod },
    };
  }

  /** Switch to a project by name — looks up path from registry and reinitializes. */
  private async handleSwitchProject(
    projectName: string,
  ): Promise<AgentToolResult<{ rpcMethod: string }>> {
    if (!this.rpcClient) throw new Error("Not connected");

    // List projects to find the path
    const projects = (await this.rpcClient.call("project.list", {})) as any[];
    const match = projects.find(
      (p: any) =>
        p.name === projectName ||
        p.name.toLowerCase() === projectName.toLowerCase(),
    );
    if (!match) {
      return {
        content: [
          { type: "text", text: JSON.stringify({ error: `Project not found: ${projectName}` }) },
        ],
        details: { rpcMethod: "project.list" },
      };
    }

    // Load the project config
    const config = (await this.rpcClient.call("project.load_config", {
      project_dir: match.path,
    })) as any;

    // Reinitialize with the new project
    this.config.projectDir = match.path;

    // Notify the TUI about the project switch
    this.onProjectSwitch?.({
      projectName: config.name || projectName,
      question: config.question || "",
      mode: config.mode || "exploratory",
      projectDir: match.path,
    });

    await this.initialize({
      projectName: config.name || projectName,
      question: config.question || "",
      mode: config.mode || "exploratory",
      dataDir: match.path + "/data",
      experimentId: "",
      currentState: `Loaded project: ${config.name}. Ready for instructions.`,
    });

    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            success: true,
            project: config.name,
            question: config.question,
            mode: config.mode,
          }),
        },
      ],
      details: { rpcMethod: "project.switch" },
    };
  }

  /**
   * Build pi-agent-core AgentTool[] scoped to current state.
   * These tools have `label` and `execute` matching the library interface.
   */
  private buildPiAgentTools(): PiAgentTool<any>[] {
    const tools: PiAgentTool<any>[] = [];

    if (!this.hasProject) {
      // No project loaded — only global tools
      tools.push({
        name: "list_projects",
        label: "List Projects",
        description:
          "List all registered Urika projects with their names and paths",
        parameters: Type.Object({}),
        execute: async (
          _toolCallId: string,
          _params: {},
          signal?: AbortSignal,
        ): Promise<AgentToolResult<any>> => {
          return this.executeRpcTool("list_projects", {});
        },
      });

      tools.push({
        name: "switch_project",
        label: "Switch Project",
        description:
          "Load/switch to a project by name. Call this when the user wants to open a project.",
        parameters: Type.Object({
          name: Type.String({ description: "Project name to load" }),
        }),
        execute: async (
          _toolCallId: string,
          params: { name: string },
          signal?: AbortSignal,
        ): Promise<AgentToolResult<any>> => {
          return this.executeRpcTool("switch_project", params);
        },
      });

      return tools;
    }

    // Project loaded — agent tools + state tools

    // Agent sub-agent tools
    for (const agentDef of this.agentTools) {
      tools.push({
        name: agentDef.name,
        label: agentDef.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
        description: agentDef.description,
        parameters: Type.Object({
          instructions: Type.String({
            description: "Instructions for the agent",
          }),
        }),
        execute: async (
          _toolCallId: string,
          params: { instructions: string },
          signal?: AbortSignal,
        ): Promise<AgentToolResult<any>> => {
          return this.executeAgentSubagent(
            agentDef,
            params.instructions,
            signal,
          );
        },
      });
    }

    // RPC state tools
    tools.push({
      name: "list_experiments",
      label: "List Experiments",
      description: "List all experiments in the current project",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("list_experiments", {}),
    });

    tools.push({
      name: "create_experiment",
      label: "Create Experiment",
      description: "Create a new experiment in the project",
      parameters: Type.Object({
        name: Type.String({ description: "Experiment name" }),
        hypothesis: Type.String({ description: "Hypothesis to test" }),
      }),
      execute: async (_id: string, params: { name: string; hypothesis: string }) =>
        this.executeRpcTool("create_experiment", params),
    });

    tools.push({
      name: "load_progress",
      label: "Load Progress",
      description:
        "Load progress for an experiment — returns all runs and status",
      parameters: Type.Object({
        experiment_id: Type.String({
          description: "Experiment ID (e.g. exp-001)",
        }),
      }),
      execute: async (_id: string, params: { experiment_id: string }) =>
        this.executeRpcTool("load_progress", params),
    });

    tools.push({
      name: "get_best_run",
      label: "Get Best Run",
      description: "Find the best run by a specific metric",
      parameters: Type.Object({
        experiment_id: Type.String({ description: "Experiment ID" }),
        metric: Type.String({ description: "Metric name (e.g. r2, rmse)" }),
        direction: Type.String({ description: "higher or lower" }),
      }),
      execute: async (
        _id: string,
        params: { experiment_id: string; metric: string; direction: string },
      ) => this.executeRpcTool("get_best_run", params),
    });

    tools.push({
      name: "load_criteria",
      label: "Load Criteria",
      description: "Load current success criteria for the project",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("load_criteria", {}),
    });

    tools.push({
      name: "load_methods",
      label: "Load Methods",
      description:
        "List all methods tried in the project with their metrics",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("load_methods", {}),
    });

    tools.push({
      name: "append_run",
      label: "Append Run",
      description: "Record a completed run result",
      parameters: Type.Object({
        experiment_id: Type.String({ description: "Experiment ID" }),
        run: Type.Object({
          run_id: Type.String(),
          method: Type.String(),
          params: Type.Any(),
          metrics: Type.Any(),
          hypothesis: Type.String(),
          observation: Type.String(),
        }),
      }),
      execute: async (_id: string, params: { experiment_id: string; run: any }) =>
        this.executeRpcTool("append_run", params),
    });

    tools.push({
      name: "finalize_project",
      label: "Finalize Project",
      description:
        "Run the finalize pipeline: finalizer -> report -> presentation -> README. Call when all experiments are done.",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("finalize_project", {}),
    });

    // Data & knowledge tools
    tools.push({
      name: "profile_data",
      label: "Profile Data",
      description:
        "Profile the project dataset — columns, types, statistics, null counts",
      parameters: Type.Object({
        data_path: Type.String({ description: "Path to data file" }),
      }),
      execute: async (_id: string, params: { data_path: string }) =>
        this.executeRpcTool("profile_data", params),
    });

    tools.push({
      name: "search_knowledge",
      label: "Search Knowledge",
      description:
        "Search the project knowledge base for relevant papers and notes",
      parameters: Type.Object({
        query: Type.String({ description: "Search query" }),
      }),
      execute: async (_id: string, params: { query: string }) =>
        this.executeRpcTool("search_knowledge", params),
    });

    tools.push({
      name: "list_knowledge",
      label: "List Knowledge",
      description: "List all entries in the project knowledge base",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("list_knowledge", {}),
    });

    tools.push({
      name: "list_tools",
      label: "List Tools",
      description:
        "List all available analysis tools (built-in + project-specific)",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("list_tools", {}),
    });

    // Criteria management
    tools.push({
      name: "update_criteria",
      label: "Update Criteria",
      description: "Add or update project success criteria",
      parameters: Type.Object({
        criteria: Type.Any({
          description: "Criteria object with metric thresholds",
        }),
        set_by: Type.String({
          description:
            "Who set these criteria (e.g. 'user', 'advisor')",
        }),
        rationale: Type.String({
          description: "Why these criteria are appropriate",
        }),
        turn: Type.Number({
          description:
            "Current turn number (use 0 if not in a turn)",
        }),
      }),
      execute: async (
        _id: string,
        params: { criteria: any; set_by: string; rationale: string; turn: number },
      ) => this.executeRpcTool("update_criteria", params),
    });

    // Session management
    tools.push({
      name: "start_session",
      label: "Start Session",
      description: "Start an orchestration session for an experiment",
      parameters: Type.Object({
        experiment_id: Type.String({ description: "Experiment ID" }),
        max_turns: Type.Optional(
          Type.Number({ description: "Maximum turns" }),
        ),
      }),
      execute: async (
        _id: string,
        params: { experiment_id: string; max_turns?: number },
      ) => this.executeRpcTool("start_session", params),
    });

    tools.push({
      name: "pause_session",
      label: "Pause Session",
      description: "Pause a running session",
      parameters: Type.Object({
        experiment_id: Type.String({ description: "Experiment ID" }),
      }),
      execute: async (_id: string, params: { experiment_id: string }) =>
        this.executeRpcTool("pause_session", params),
    });

    // Reports
    tools.push({
      name: "generate_report",
      label: "Generate Report",
      description:
        "Generate the project results summary and key findings reports",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("generate_report", {}),
    });

    tools.push({
      name: "summarize_project",
      label: "Summarize Project",
      description:
        "Get a concise structured summary of the project — experiments, top methods, criteria status, run counts. Returns data, not prose. Use this when the user asks for a summary or overview.",
      parameters: Type.Object({}),
      execute: async (_id: string, _params: {}) =>
        this.executeRpcTool("summarize_project", {}),
    });

    return tools;
  }
}
