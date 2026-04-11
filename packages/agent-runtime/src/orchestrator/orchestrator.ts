import { join } from "path";
import type { AgentRuntime, ManagedAgent, RuntimeEvent, ToolDefinition } from "../runtime/types";
import type { SystemConfig, ToolDeclaration, AgentDeclaration } from "../config/types";
import type { RpcClient } from "../rpc/client";
import { loadPrompt } from "./prompt-loader";
import { SessionManager, type OrchestratorSession } from "./session-manager";

// ── Context ──

export interface OrchestratorContext {
  projectName: string;
  question: string;
  mode: string;
  dataDir: string;
  experimentId: string;
  currentState: string;
  /** Extra variables injected into prompt templates. */
  promptVariables?: Record<string, string>;
}

// ── Project switch callback ──

export interface ProjectSwitchResult {
  projectName: string;
  projectDir: string;
  question?: string;
  mode?: string;
}

export type OnProjectSwitch = (
  projectDir: string,
) => Promise<ProjectSwitchResult>;

// ── Generic Orchestrator ──

/**
 * Config-driven orchestrator.
 *
 * Reads tools, agents, and prompt configuration from a SystemConfig (parsed
 * from runtime.toml) and builds an agent via the supplied AgentRuntime.
 *
 * Tool executors are generated at construction time:
 * - Tools with `rpcMethod` get executors that call the RPC client.
 * - Tools with `special === "switch_project"` trigger a project switch flow.
 * - Agent declarations become sub-agent tools (the orchestrator can delegate to them).
 */
export class GenericOrchestrator {
  private runtime: AgentRuntime;
  private rpcClient: RpcClient;
  private config: SystemConfig;
  private agent: ManagedAgent | null = null;
  private hasProject = false;
  private projectDir = "";
  private listeners: Set<(event: RuntimeEvent) => void> = new Set();
  /** Agent-level unsubscribe functions, keyed by listener. */
  private agentUnsubs: Map<(event: RuntimeEvent) => void, () => void> = new Map();
  /** Session manager for conversation persistence. */
  private sessionManager: SessionManager;

  /** Called when a project switch tool is invoked. */
  onProjectSwitch?: OnProjectSwitch;

  constructor(
    runtime: AgentRuntime,
    rpcClient: RpcClient,
    config: SystemConfig,
  ) {
    this.runtime = runtime;
    this.rpcClient = rpcClient;
    this.config = config;
    this.sessionManager = new SessionManager(rpcClient, "");
  }

  /** Get the session manager for resume/list operations. */
  getSessionManager(): SessionManager {
    return this.sessionManager;
  }

  // ── Public API ──

  /**
   * Initialize (or reinitialize) the orchestrator with project context.
   *
   * Builds the system prompt, assembles scoped tools, and creates
   * a ManagedAgent via the runtime backend.
   */
  async initialize(context: OrchestratorContext): Promise<void> {
    this.hasProject =
      context.projectName !== "" &&
      context.projectName !== "No project selected";

    if (context.dataDir) {
      this.projectDir = context.dataDir.replace(/\/data\/?$/, "") || context.dataDir;
      this.sessionManager.setProjectDir(this.projectDir);
    }

    // Build system prompt
    const prompt = this.buildPrompt(context);

    // Build tools + executors
    const { tools, executors } = this.buildTools();

    // Resolve model
    const model =
      this.config.orchestrator.modelOverride ?? this.config.runtime.defaultModel;

    this.agent = this.runtime.createAgent({
      name: "orchestrator",
      systemPrompt: prompt,
      tools,
      model,
      toolExecutors: executors,
    });

    // Re-subscribe all existing listeners to the new agent
    for (const listener of this.listeners) {
      this.subscribeAgentListener(listener);
    }

    // Internal subscription: auto-save session on agent_end
    // Capture current agent + project dir in closure to avoid races on re-init.
    const currentAgent = this.agent;
    const currentProjectDir = this.projectDir;
    const wasProjectLoaded = this.hasProject;
    currentAgent.subscribe((event: RuntimeEvent) => {
      if (event.type !== "agent_end" || !wasProjectLoaded) return;
      // Only save if we're still working with the same project
      if (this.projectDir !== currentProjectDir) return;
      const messages = currentAgent.getMessages?.() ?? [];
      if (messages.length === 0) return;
      this.sessionManager.saveMessages(messages).catch((err) => {
        console.error("Failed to save session:", err?.message ?? err);
      });
    });
  }

  /**
   * Resume a previously saved session — replaces current conversation history.
   * Returns true if the runtime supports resume, false otherwise.
   */
  async resumeSession(session: OrchestratorSession): Promise<boolean> {
    this.sessionManager.setCurrentSession(session);

    if (!this.agent) return false;
    if (typeof this.agent.setMessages !== "function") {
      // Runtime doesn't support message replacement (e.g. ClaudeRuntime)
      return false;
    }

    if (session.recent_messages.length > 0) {
      this.agent.setMessages(session.recent_messages);
    }
    return true;
  }

  /** Start a new (empty) session — clears current conversation. */
  startNewSession(): boolean {
    this.sessionManager.clearCurrentSession();
    this.sessionManager.newSession();
    if (!this.agent) return false;
    if (typeof this.agent.setMessages !== "function") return false;
    this.agent.setMessages([]);
    return true;
  }

  /** Send a user message to the orchestrator agent. */
  async processMessage(message: string): Promise<void> {
    if (!this.agent) {
      throw new Error(
        "Orchestrator not initialized — call initialize() first",
      );
    }
    await this.agent.prompt(message);
  }

  /** Subscribe to runtime events (text deltas, tool calls, etc.). */
  subscribe(listener: (event: RuntimeEvent) => void): () => void {
    this.listeners.add(listener);
    if (this.agent) {
      this.subscribeAgentListener(listener);
    }
    return () => {
      this.listeners.delete(listener);
      const agentUnsub = this.agentUnsubs.get(listener);
      if (agentUnsub) {
        agentUnsub();
        this.agentUnsubs.delete(listener);
      }
    };
  }

  /** Inject a steering message mid-run. */
  steer(message: string): void {
    this.agent?.steer(message);
  }

  /** Abort the current agent run. */
  abort(): void {
    this.agent?.abort();
  }

  /** Shut down the orchestrator and RPC client. */
  close(): void {
    this.agent?.abort();
  }

  /** Whether a project is currently loaded. */
  get projectLoaded(): boolean {
    return this.hasProject;
  }

  /** Current project directory. */
  get currentProjectDir(): string {
    return this.projectDir;
  }

  // ── Private ──

  /** Subscribe a single listener to the current agent, tracking the unsub. */
  private subscribeAgentListener(listener: (event: RuntimeEvent) => void): void {
    if (!this.agent) return;
    // Remove previous agent subscription if any (e.g. on reinitialize)
    const prevUnsub = this.agentUnsubs.get(listener);
    if (prevUnsub) prevUnsub();
    const unsub = this.agent.subscribe(listener);
    this.agentUnsubs.set(listener, unsub);
  }

  /**
   * Build the orchestrator system prompt from the prompts directory.
   * Falls back to a minimal prompt if the file is missing.
   */
  private buildPrompt(ctx: OrchestratorContext): string {
    const promptFile = this.config.orchestrator.prompt;
    const promptsDir = this.config.system.promptsDir;

    const variables: Record<string, string> = {
      project_name: ctx.projectName,
      question: ctx.question,
      mode: ctx.mode,
      data_dir: ctx.dataDir,
      experiment_id: ctx.experimentId,
      current_state: ctx.currentState,
      ...ctx.promptVariables,
    };

    try {
      return loadPrompt(join(promptsDir, promptFile), variables);
    } catch {
      return [
        `You are the ${this.config.system.name} orchestrator.`,
        ctx.projectName ? `Project: ${ctx.projectName}.` : "No project selected.",
        ctx.currentState,
      ]
        .filter(Boolean)
        .join(" ");
    }
  }

  /**
   * Build tool definitions and executor functions from config.
   *
   * Scoping rules:
   * - "global" tools are always available.
   * - "project" tools are only available when a project is loaded.
   * - Agent sub-agent tools are only available when a project is loaded.
   */
  private buildTools(): {
    tools: ToolDefinition[];
    executors: Record<string, (args: any, signal?: AbortSignal) => Promise<any>>;
  } {
    const tools: ToolDefinition[] = [];
    const executors: Record<string, (args: any, signal?: AbortSignal) => Promise<any>> = {};

    // RPC-backed tools from config
    for (const decl of this.config.tools) {
      if (decl.scope === "project" && !this.hasProject) continue;

      const toolDef = this.toolDeclToDefinition(decl);
      tools.push(toolDef);

      if (decl.special === "switch_project") {
        executors[decl.name] = (args) => this.executeSwitchProject(args);
      } else {
        executors[decl.name] = (args) => this.executeRpcTool(decl.rpcMethod, args);
      }
    }

    // Agent tools (project-only) — executed via RPC to Python backend
    // Python agents get full Claude SDK tools (Read, Write, Bash, Glob, Grep)
    if (this.hasProject) {
      for (const agentDecl of this.config.agents) {
        const toolDef = this.agentDeclToTool(agentDecl);
        tools.push(toolDef);
        executors[agentDecl.name] = (args) =>
          this.executeAgentRpc(agentDecl.name, args.instructions ?? args.input ?? "");
      }
    }

    return { tools, executors };
  }

  /** Convert a ToolDeclaration (from config) to a ToolDefinition (runtime type). */
  private toolDeclToDefinition(decl: ToolDeclaration): ToolDefinition {
    const params: Record<string, { type: any; description?: string; optional?: boolean }> = {};
    if (decl.params) {
      for (const [key, param] of Object.entries(decl.params)) {
        params[key] = {
          type: param.type as any,
          description: param.description,
          optional: param.optional,
        };
      }
    }

    return {
      name: decl.name,
      description: decl.description,
      scope: decl.scope,
      params: Object.keys(params).length > 0 ? params : undefined,
      rpcMethod: decl.rpcMethod,
      special: decl.special,
    };
  }

  /** Create a ToolDefinition for an agent sub-agent. */
  private agentDeclToTool(decl: AgentDeclaration): ToolDefinition {
    return {
      name: decl.name,
      description: decl.description,
      scope: "project",
      params: {
        instructions: {
          type: "string",
          description: "Instructions for the agent",
        },
      },
    };
  }

  /** Execute an RPC tool call, injecting project_dir automatically. */
  private async executeRpcTool(
    rpcMethod: string,
    args: Record<string, any>,
  ): Promise<string> {
    const params = { ...args, project_dir: this.projectDir };
    const result = await this.rpcClient.call(rpcMethod, params);
    return typeof result === "string" ? result : JSON.stringify(result);
  }

  /** Handle the special switch_project tool. */
  private async executeSwitchProject(
    args: Record<string, any>,
  ): Promise<string> {
    const projectName = args.name ?? args.path ?? "";

    if (this.onProjectSwitch) {
      // Delegate to the host's project switch handler
      const result = await this.onProjectSwitch(projectName);
      this.projectDir = result.projectDir;
      this.hasProject = true;

      // Reinitialize with new project context
      await this.initialize({
        projectName: result.projectName,
        question: result.question ?? "",
        mode: result.mode ?? "exploratory",
        dataDir: result.projectDir + "/data",
        experimentId: "",
        currentState: `Loaded project: ${result.projectName}. Ready for instructions.`,
      });

      return JSON.stringify({
        success: true,
        project: result.projectName,
        projectDir: result.projectDir,
      });
    }

    // Fallback: use RPC to list and find the project
    const projects = (await this.rpcClient.call("project.list", {})) as any[];
    const match = projects.find(
      (p: any) =>
        p.name === projectName ||
        p.name?.toLowerCase() === projectName.toLowerCase() ||
        p.path === projectName,
    );

    if (!match) {
      return JSON.stringify({ error: `Project not found: ${projectName}` });
    }

    this.projectDir = match.path;
    this.hasProject = true;

    await this.initialize({
      projectName: match.name ?? projectName,
      question: match.question ?? "",
      mode: match.mode ?? "exploratory",
      dataDir: match.path + "/data",
      experimentId: "",
      currentState: `Loaded project: ${match.name}. Ready for instructions.`,
    });

    return JSON.stringify({
      success: true,
      project: match.name,
      projectDir: match.path,
    });
  }

  /**
   * Execute an agent via RPC — calls the Python backend which runs the agent
   * with full Claude SDK tools (Read, Write, Bash, Glob, Grep).
   *
   * This replaces the old `executeSubAgent` which used PiRuntime and had
   * no tools. The Python backend's `agent.run` method uses `AgentRegistry`
   * to find the role, `build_config()` to get the proper tools/prompts,
   * and `get_runner()` to execute via the Claude Agent SDK.
   */
  private async executeAgentRpc(
    agentName: string,
    instructions: string,
  ): Promise<string> {
    const result = await this.rpcClient.call("agent.run", {
      project_dir: this.projectDir,
      agent_name: agentName,
      prompt: instructions,
      experiment_id: "",
    }) as any;

    if (!result.success) {
      throw new Error(result.error || `Agent ${agentName} failed`);
    }

    return result.text_output || "No output from agent.";
  }
}
