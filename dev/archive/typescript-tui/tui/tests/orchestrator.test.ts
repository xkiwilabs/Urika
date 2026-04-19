import { describe, expect, it } from "bun:test";
import { Orchestrator } from "../src/orchestrator/orchestrator";

const DEFAULT_CONFIG = {
  projectDir: "/tmp/test",
  promptsDir: "/nonexistent",
  defaultModel: "anthropic/claude-sonnet-4-6",
  modelOverrides: {},
  pythonCommand: "python",
};

describe("Orchestrator", () => {
  it("can be constructed with config", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    expect(orch).toBeDefined();
  });

  it("only has global tools before project is loaded", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    const names = orch.getToolNames();
    expect(names).toContain("list_projects");
    expect(names).toContain("switch_project");
    expect(names).not.toContain("planning_agent");
    expect(names).not.toContain("list_experiments");
    expect(names).toHaveLength(2);
  });

  it("has all tools after project is initialized", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    await orch.initialize({
      projectName: "test-project",
      question: "Does X predict Y?",
      mode: "exploratory",
      dataDir: "/tmp/test/data",
      experimentId: "",
      currentState: "Ready.",
    });
    const names = orch.getToolNames();

    // Agent tools (10 roles — project_summarizer is now an RPC tool)
    expect(names).toContain("planning_agent");
    expect(names).toContain("task_agent");
    expect(names).toContain("evaluator");
    expect(names).toContain("advisor");
    expect(names).toContain("presentation_agent");
    expect(names).toContain("finalizer");
    expect(names).not.toContain("project_summarizer"); // now an RPC tool

    // State tools
    expect(names).not.toContain("list_projects");
    expect(names).toContain("list_experiments");
    expect(names).toContain("create_experiment");
    expect(names).toContain("load_progress");
    expect(names).toContain("load_criteria");
    expect(names).toContain("load_methods");
    expect(names).toContain("finalize_project");
    expect(names).toContain("profile_data");
    expect(names).toContain("search_knowledge");
    expect(names).toContain("list_knowledge");
    expect(names).toContain("list_tools");
    expect(names).toContain("update_criteria");
    expect(names).toContain("start_session");
    expect(names).toContain("pause_session");
    expect(names).toContain("generate_report");
    expect(names).toContain("summarize_project");
  });

  it("creates an Agent after initialize", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    expect(orch.getAgent()).toBeNull();

    await orch.initialize({
      projectName: "test-project",
      question: "Does X predict Y?",
      mode: "exploratory",
      dataDir: "/tmp/test/data",
      experimentId: "",
      currentState: "Ready.",
    });

    expect(orch.getAgent()).toBeDefined();
    expect(orch.getAgent()).not.toBeNull();
  });

  it("agent has correct tools after initialize", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    await orch.initialize({
      projectName: "test-project",
      question: "Q?",
      mode: "exploratory",
      dataDir: "/tmp/test/data",
      experimentId: "",
      currentState: "Ready.",
    });

    const agent = orch.getAgent()!;
    const toolNames = agent.state.tools.map((t) => t.name);

    // Should have agent tools + RPC state tools
    expect(toolNames).toContain("planning_agent");
    expect(toolNames).toContain("task_agent");
    expect(toolNames).toContain("list_experiments");
    expect(toolNames).toContain("summarize_project");

    // All tools should have labels
    for (const tool of agent.state.tools) {
      expect(tool.label).toBeDefined();
      expect(typeof tool.label).toBe("string");
      expect(tool.label.length).toBeGreaterThan(0);
    }
  });

  it("agent has only global tools before project is loaded", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    await orch.initialize({
      projectName: "No project selected",
      question: "",
      mode: "exploratory",
      dataDir: "",
      experimentId: "",
      currentState: "No project.",
    });

    const agent = orch.getAgent()!;
    const toolNames = agent.state.tools.map((t) => t.name);

    expect(toolNames).toContain("list_projects");
    expect(toolNames).toContain("switch_project");
    expect(toolNames).not.toContain("planning_agent");
    expect(toolNames).toHaveLength(2);
  });

  it("supports subscribe after initialize", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    await orch.initialize({
      projectName: "test",
      question: "Q?",
      mode: "exploratory",
      dataDir: "/tmp/test/data",
      experimentId: "",
      currentState: "Ready.",
    });

    const events: string[] = [];
    const unsub = orch.subscribe((event) => {
      events.push(event.type);
    });

    expect(typeof unsub).toBe("function");
    // Clean up
    unsub();
  });

  it("close is safe to call without connect", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    orch.close();
  });

  it("clears agent on initialize (project switch)", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    await orch.initialize({
      projectName: "project-a",
      question: "Q1",
      mode: "exploratory",
      dataDir: "/tmp/a/data",
      experimentId: "",
      currentState: "Ready.",
    });
    const agent1 = orch.getAgent();

    // Re-initialize (project switch) — should create a new agent
    await orch.initialize({
      projectName: "project-b",
      question: "Q2",
      mode: "exploratory",
      dataDir: "/tmp/b/data",
      experimentId: "",
      currentState: "Switched.",
    });
    const agent2 = orch.getAgent();

    expect(agent2).not.toBe(agent1);
    expect(orch.getToolNames()).toContain("planning_agent");
  });

  it("steer and abort are safe to call before initialize", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    // Should not throw
    orch.steer("hello");
    orch.abort();
  });
});
