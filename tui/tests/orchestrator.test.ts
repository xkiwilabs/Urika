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
    expect(names).not.toContain("create_experiment");
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

    // Agent tools (8 roles)
    expect(names).toContain("planning_agent");
    expect(names).toContain("task_agent");
    expect(names).toContain("evaluator");
    expect(names).toContain("advisor");

    // State tools
    expect(names).toContain("list_projects");
    expect(names).toContain("list_experiments");
    expect(names).toContain("create_experiment");
    expect(names).toContain("load_progress");
    expect(names).toContain("load_criteria");
    expect(names).toContain("load_methods");
    expect(names).toContain("finalize_project");
  });

  it("accepts event handlers without throwing", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    orch.setEvents({
      onAgentStart: (_name) => {},
      onAgentOutput: (_name, _text) => {},
      onAgentEnd: (_name) => {},
      onText: (_text) => {},
      onToolCall: (_name, _args) => {},
      onError: (_error) => {},
    });
  });

  it("close is safe to call without connect", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    orch.close();
  });

  it("clears messages on initialize", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    await orch.initialize({
      projectName: "project-a",
      question: "Q1",
      mode: "exploratory",
      dataDir: "/tmp/a/data",
      experimentId: "",
      currentState: "Ready.",
    });
    // Re-initialize (project switch) should not crash
    await orch.initialize({
      projectName: "project-b",
      question: "Q2",
      mode: "exploratory",
      dataDir: "/tmp/b/data",
      experimentId: "",
      currentState: "Switched.",
    });
    expect(orch.getToolNames()).toContain("planning_agent");
  });
});
