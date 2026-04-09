import { getModel, completeSimple, Type } from "@mariozechner/pi-ai";
import type {
  Model,
  Context,
  Tool,
  Message,
  AssistantMessage,
  ToolCall,
  ToolResultMessage,
  TextContent,
  Api,
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

export interface OrchestratorEvents {
  onAgentStart?: (agent: string) => void;
  onAgentOutput?: (agent: string, text: string) => void;
  onAgentEnd?: (agent: string) => void;
  onText?: (text: string) => void;
  onToolCall?: (name: string, args: Record<string, any>) => void;
  onError?: (error: string) => void;
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
  private messages: Message[] = [];
  private events: OrchestratorEvents = {};
  private systemPrompt: string = "";
  private hasProject = false;

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

  /** Register event handlers for orchestrator activity. */
  setEvents(events: OrchestratorEvents): void {
    this.events = events;
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
    // Clear conversation history when switching projects
    this.messages = [];
  }

  /**
   * Process a user message through the orchestrator loop.
   * Returns the orchestrator's final text response.
   *
   * The loop: user message -> LLM -> tool calls -> execute -> LLM -> ... -> text response
   */
  async processMessage(userMessage: string): Promise<string> {
    this.messages.push({
      role: "user" as const,
      content: userMessage,
      timestamp: Date.now(),
    });

    const orchestratorModel =
      this.config.modelOverrides["orchestrator"] ?? this.config.defaultModel;
    const piTools = this.buildPiAiTools();

    let iterations = 0;
    const maxIterations = 50;

    while (iterations < maxIterations) {
      iterations++;

      const context: Context = {
        systemPrompt: this.systemPrompt,
        messages: this.messages,
        tools: piTools,
      };

      const model = this.resolveModel(orchestratorModel);
      const apiKey = await this.resolveApiKey();
      const response = await completeSimple(model, context, apiKey ? { apiKey } : undefined);

      this.messages.push(response);

      const toolCalls = response.content.filter(
        (c): c is ToolCall => c.type === "toolCall",
      );

      if (toolCalls.length === 0) {
        const text = this.extractText(response);
        this.events.onText?.(text);
        return text;
      }

      // Execute each tool call and feed results back
      for (const toolCall of toolCalls) {
        this.events.onToolCall?.(toolCall.name, toolCall.arguments);

        let result: string;
        let isError = false;
        try {
          result = await this.executeTool(toolCall.name, toolCall.arguments);
        } catch (err: any) {
          result = `Error: ${err.message}`;
          isError = true;
          this.events.onError?.(err.message);
        }

        const toolResult: ToolResultMessage = {
          role: "toolResult",
          toolCallId: toolCall.id,
          toolName: toolCall.name,
          content: [{ type: "text", text: result }],
          isError,
          timestamp: Date.now(),
        };
        this.messages.push(toolResult);
      }
      // Loop — LLM sees tool results and decides next action
    }

    throw new Error("Orchestrator exceeded maximum iterations");
  }

  /** Shut down the RPC subprocess. */
  close(): void {
    this.rpcClient?.close();
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  /** Route a tool call to the correct executor. */
  private async executeTool(
    name: string,
    args: Record<string, any>,
  ): Promise<string> {
    const agentTool = this.agentTools.find((t) => t.name === name);
    if (agentTool) {
      this.events.onAgentStart?.(name);
      const result = await this.executeAgentTool(
        agentTool,
        args.instructions ?? "",
      );
      this.events.onAgentEnd?.(name);
      return result;
    }

    return this.executeRpcTool(name, args);
  }

  /** Run an agent via pi-ai with the agent's own model and system prompt. */
  private async executeAgentTool(
    agent: AgentTool,
    instructions: string,
  ): Promise<string> {
    const model = this.resolveModel(agent.model);
    const apiKey = await this.resolveApiKey();

    const context: Context = {
      systemPrompt: agent.systemPrompt,
      messages: [
        { role: "user" as const, content: instructions, timestamp: Date.now() },
      ],
    };

    const response = await completeSimple(model, context, apiKey ? { apiKey } : undefined);
    const text = this.extractText(response);
    this.events.onAgentOutput?.(agent.name, text);
    return text;
  }

  /** Call the Python RPC server for state operations. */
  private async executeRpcTool(
    name: string,
    args: Record<string, any>,
  ): Promise<string> {
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
    return JSON.stringify(result);
  }

  /** Switch to a project by name — looks up path from registry and reinitializes. */
  private async handleSwitchProject(projectName: string): Promise<string> {
    if (!this.rpcClient) throw new Error("Not connected");

    // List projects to find the path
    const projects = await this.rpcClient.call("project.list", {}) as any[];
    const match = projects.find(
      (p: any) => p.name === projectName || p.name.toLowerCase() === projectName.toLowerCase()
    );
    if (!match) {
      return JSON.stringify({ error: `Project not found: ${projectName}` });
    }

    // Load the project config
    const config = await this.rpcClient.call("project.load_config", {
      project_dir: match.path,
    }) as any;

    // Reinitialize with the new project
    this.config.projectDir = match.path;
    await this.initialize({
      projectName: config.name || projectName,
      question: config.question || "",
      mode: config.mode || "exploratory",
      dataDir: match.path + "/data",
      experimentId: "",
      currentState: `Loaded project: ${config.name}. Ready for instructions.`,
    });

    this.events.onText?.(`Switched to project: ${config.name}`);

    return JSON.stringify({
      success: true,
      project: config.name,
      question: config.question,
      mode: config.mode,
    });
  }

  /** Resolve an API key via the configured callback, if any. */
  private async resolveApiKey(): Promise<string | null> {
    if (!this.config.getApiKey) return null;
    return this.config.getApiKey();
  }

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

  /** Extract text from an AssistantMessage. */
  private extractText(msg: AssistantMessage): string {
    return msg.content
      .filter((c): c is TextContent => c.type === "text")
      .map((c) => c.text)
      .join("\n");
  }

  /** Build the pi-ai Tool array scoped to current state. */
  private buildPiAiTools(): Tool[] {
    const tools: Tool[] = [];

    if (!this.hasProject) {
      // No project loaded — only global tools
      tools.push({
        name: "list_projects",
        description: "List all registered Urika projects with their names and paths",
        parameters: Type.Object({}),
      });

      tools.push({
        name: "switch_project",
        description: "Load/switch to a project by name. Call this when the user wants to open a project.",
        parameters: Type.Object({
          name: Type.String({ description: "Project name to load" }),
        }),
      });

      return tools;
    }

    // Project loaded — project-focused tools only
    {
      // Agent tools
      for (const agent of this.agentTools) {
        tools.push({
          name: agent.name,
          description: agent.description,
          parameters: Type.Object({
            instructions: Type.String({ description: "Instructions for the agent" }),
          }),
        });
      }

      // State tools
      tools.push({
        name: "list_experiments",
        description: "List all experiments in the current project",
        parameters: Type.Object({}),
      });

      tools.push({
        name: "create_experiment",
        description: "Create a new experiment in the project",
        parameters: Type.Object({
          name: Type.String({ description: "Experiment name" }),
          hypothesis: Type.String({ description: "Hypothesis to test" }),
        }),
      });

      tools.push({
        name: "load_progress",
        description: "Load progress for an experiment — returns all runs and status",
        parameters: Type.Object({
          experiment_id: Type.String({ description: "Experiment ID (e.g. exp-001)" }),
        }),
      });

      tools.push({
        name: "get_best_run",
        description: "Find the best run by a specific metric",
        parameters: Type.Object({
          experiment_id: Type.String({ description: "Experiment ID" }),
          metric: Type.String({ description: "Metric name (e.g. r2, rmse)" }),
          direction: Type.String({ description: "higher or lower" }),
        }),
      });

      tools.push({
        name: "load_criteria",
        description: "Load current success criteria for the project",
        parameters: Type.Object({}),
      });

      tools.push({
        name: "load_methods",
        description: "List all methods tried in the project with their metrics",
        parameters: Type.Object({}),
      });

      tools.push({
        name: "append_run",
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
      });

      tools.push({
        name: "finalize_project",
        description: "Run the finalize pipeline: finalizer -> report -> presentation -> README. Call when all experiments are done.",
        parameters: Type.Object({}),
      });

      // Data & knowledge tools
      tools.push({
        name: "profile_data",
        description: "Profile the project dataset — columns, types, statistics, null counts",
        parameters: Type.Object({
          data_path: Type.String({ description: "Path to data file" }),
        }),
      });

      tools.push({
        name: "search_knowledge",
        description: "Search the project knowledge base for relevant papers and notes",
        parameters: Type.Object({
          query: Type.String({ description: "Search query" }),
        }),
      });

      tools.push({
        name: "list_knowledge",
        description: "List all entries in the project knowledge base",
        parameters: Type.Object({}),
      });

      tools.push({
        name: "list_tools",
        description: "List all available analysis tools (built-in + project-specific)",
        parameters: Type.Object({}),
      });

      // Criteria management
      tools.push({
        name: "update_criteria",
        description: "Add or update project success criteria",
        parameters: Type.Object({
          criteria: Type.Any({ description: "Criteria object with metric thresholds" }),
          rationale: Type.String({ description: "Why these criteria are appropriate" }),
          turn: Type.Number({ description: "Current turn number" }),
        }),
      });

      // Session management
      tools.push({
        name: "start_session",
        description: "Start an orchestration session for an experiment",
        parameters: Type.Object({
          experiment_id: Type.String({ description: "Experiment ID" }),
          max_turns: Type.Optional(Type.Number({ description: "Maximum turns" })),
        }),
      });

      tools.push({
        name: "pause_session",
        description: "Pause a running session",
        parameters: Type.Object({
          experiment_id: Type.String({ description: "Experiment ID" }),
        }),
      });

      // Reports
      tools.push({
        name: "generate_report",
        description: "Generate the project results summary and key findings reports",
        parameters: Type.Object({}),
      });

      tools.push({
        name: "summarize_project",
        description: "Get a concise structured summary of the project — experiments, top methods, criteria status, run counts. Returns data, not prose. Use this when the user asks for a summary or overview.",
        parameters: Type.Object({}),
      });
    }

    return tools;
  }
}
