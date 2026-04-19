import { describe, expect, it, mock } from "bun:test";
import { GenericOrchestrator } from "../src/orchestrator/orchestrator";
import type { SystemConfig } from "../src/config/types";
import type {
  AgentRuntime,
  ManagedAgent,
  AgentConfig,
  RuntimeEvent,
} from "../src/runtime/types";
import type { RpcClient } from "../src/rpc/client";

// ── Mock ManagedAgent ──

function createMockAgent(): ManagedAgent & {
  _lastMessage: string;
  _listeners: Set<(event: RuntimeEvent) => void>;
} {
  const listeners = new Set<(event: RuntimeEvent) => void>();
  return {
    _lastMessage: "",
    _listeners: listeners,
    isRunning: false,
    async prompt(message: string) {
      this._lastMessage = message;
    },
    subscribe(listener: (event: RuntimeEvent) => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    steer(_message: string) {},
    abort() {},
  };
}

// ── Mock Runtime ──

function createMockRuntime(): AgentRuntime & { _lastConfig: AgentConfig | null; _agent: ReturnType<typeof createMockAgent> } {
  const agent = createMockAgent();
  return {
    name: "pi" as const,
    _lastConfig: null,
    _agent: agent,
    async authenticate() {},
    isAuthenticated() { return true; },
    getAuthStatus() { return { provider: "mock", method: "api-key" as const, active: true }; },
    createAgent(config: AgentConfig) {
      this._lastConfig = config;
      return agent;
    },
    listModels() { return []; },
    getDefaultModel() { return "mock/model"; },
  };
}

// ── Mock RpcClient ──

function createMockRpcClient(): RpcClient & { _calls: Array<{ method: string; params: any }> } {
  return {
    _calls: [],
    async call(method: string, params: any) {
      this._calls.push({ method, params });
      return { ok: true };
    },
    close() {},
  } as any;
}

// ── Minimal config ──

function minimalConfig(overrides?: Partial<SystemConfig>): SystemConfig {
  return {
    system: {
      name: "TestApp",
      version: "1.0.0",
      description: "Test",
      rpcCommand: "echo noop",
      promptsDir: "/tmp/nonexistent-prompts",
    },
    runtime: {
      defaultBackend: "pi",
      defaultModel: "anthropic/claude-sonnet-4-6",
      models: {},
    },
    privacy: {
      mode: "open",
      localAgents: [],
    },
    agents: [],
    tools: [
      {
        name: "list_projects",
        rpcMethod: "project.list",
        description: "List projects",
        scope: "global",
      },
      {
        name: "switch_project",
        rpcMethod: "",
        description: "Switch project",
        scope: "global",
        special: "switch_project",
        params: { name: { type: "string", description: "Project name" } },
      },
      {
        name: "list_experiments",
        rpcMethod: "experiment.list",
        description: "List experiments",
        scope: "project",
      },
    ],
    commands: [],
    orchestrator: {
      prompt: "orchestrator_system.md",
    },
    ...overrides,
  };
}

// ── Tests ──

describe("GenericOrchestrator", () => {
  it("initializes with no project and creates agent", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const config = minimalConfig();
    const orch = new GenericOrchestrator(runtime, rpc, config);

    await orch.initialize({
      projectName: "",
      question: "",
      mode: "exploratory",
      dataDir: "",
      experimentId: "",
      currentState: "No project selected.",
    });

    expect(runtime._lastConfig).not.toBeNull();
    expect(runtime._lastConfig!.name).toBe("orchestrator");
    expect(orch.projectLoaded).toBe(false);
  });

  it("includes only global tools when no project is loaded", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const config = minimalConfig();
    const orch = new GenericOrchestrator(runtime, rpc, config);

    await orch.initialize({
      projectName: "",
      question: "",
      mode: "exploratory",
      dataDir: "",
      experimentId: "",
      currentState: "No project selected.",
    });

    const tools = runtime._lastConfig!.tools;
    const toolNames = tools.map((t) => t.name);
    expect(toolNames).toContain("list_projects");
    expect(toolNames).toContain("switch_project");
    expect(toolNames).not.toContain("list_experiments"); // project-scoped
  });

  it("includes project tools + agent tools when project is loaded", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const config = minimalConfig({
      agents: [
        {
          name: "planning_agent",
          prompt: "planning.md",
          description: "Plans experiments",
        },
      ],
    });
    const orch = new GenericOrchestrator(runtime, rpc, config);

    await orch.initialize({
      projectName: "test-project",
      question: "What predicts outcome?",
      mode: "exploratory",
      dataDir: "/tmp/project/data",
      experimentId: "",
      currentState: "Loaded.",
    });

    const tools = runtime._lastConfig!.tools;
    const toolNames = tools.map((t) => t.name);
    expect(toolNames).toContain("list_projects");
    expect(toolNames).toContain("list_experiments");
    expect(toolNames).toContain("planning_agent");
    expect(orch.projectLoaded).toBe(true);
  });

  it("processMessage throws if not initialized", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const orch = new GenericOrchestrator(runtime, rpc, minimalConfig());

    await expect(orch.processMessage("hello")).rejects.toThrow(
      "not initialized",
    );
  });

  it("processMessage delegates to agent.prompt", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const orch = new GenericOrchestrator(runtime, rpc, minimalConfig());

    await orch.initialize({
      projectName: "",
      question: "",
      mode: "",
      dataDir: "",
      experimentId: "",
      currentState: "",
    });

    await orch.processMessage("hello world");
    expect(runtime._agent._lastMessage).toBe("hello world");
  });

  it("subscribe returns unsubscribe function", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const orch = new GenericOrchestrator(runtime, rpc, minimalConfig());

    await orch.initialize({
      projectName: "",
      question: "",
      mode: "",
      dataDir: "",
      experimentId: "",
      currentState: "",
    });

    const events: RuntimeEvent[] = [];
    const unsub = orch.subscribe((e) => events.push(e));

    // Emit via mock agent
    for (const listener of runtime._agent._listeners) {
      listener({ type: "text_delta", delta: "hi" });
    }
    expect(events).toHaveLength(1);

    unsub();
    for (const listener of runtime._agent._listeners) {
      listener({ type: "text_delta", delta: "bye" });
    }
    // Listener was removed
    expect(events).toHaveLength(1);
  });

  it("builds tool executors that call RPC client", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const orch = new GenericOrchestrator(runtime, rpc, minimalConfig());

    await orch.initialize({
      projectName: "",
      question: "",
      mode: "",
      dataDir: "",
      experimentId: "",
      currentState: "",
    });

    // The tool executors should be on the config
    const executors = runtime._lastConfig!.toolExecutors!;
    expect(executors.list_projects).toBeDefined();

    // Call it
    const result = await executors.list_projects({});
    expect(rpc._calls).toHaveLength(1);
    expect(rpc._calls[0].method).toBe("project.list");
  });

  it("uses fallback prompt when prompts dir is missing", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const orch = new GenericOrchestrator(runtime, rpc, minimalConfig());

    await orch.initialize({
      projectName: "test",
      question: "",
      mode: "",
      dataDir: "",
      experimentId: "",
      currentState: "Ready.",
    });

    // Should use fallback prompt (prompts dir doesn't exist)
    expect(runtime._lastConfig!.systemPrompt).toContain("TestApp");
    expect(runtime._lastConfig!.systemPrompt).toContain("test");
  });

  it("uses model override from orchestrator config", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const config = minimalConfig({
      orchestrator: {
        prompt: "orchestrator_system.md",
        modelOverride: "anthropic/claude-opus-4-6",
      },
    });
    const orch = new GenericOrchestrator(runtime, rpc, config);

    await orch.initialize({
      projectName: "",
      question: "",
      mode: "",
      dataDir: "",
      experimentId: "",
      currentState: "",
    });

    expect(runtime._lastConfig!.model).toBe("anthropic/claude-opus-4-6");
  });

  it("extracts projectDir from dataDir", async () => {
    const runtime = createMockRuntime();
    const rpc = createMockRpcClient();
    const orch = new GenericOrchestrator(runtime, rpc, minimalConfig());

    await orch.initialize({
      projectName: "test",
      question: "",
      mode: "",
      dataDir: "/home/user/projects/test/data",
      experimentId: "",
      currentState: "",
    });

    expect(orch.currentProjectDir).toBe("/home/user/projects/test");
  });
});
