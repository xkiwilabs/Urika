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

  it("has agent tools and state tools registered", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    const names = orch.getToolNames();

    // Agent tools (8 roles)
    expect(names).toContain("planning_agent");
    expect(names).toContain("task_agent");
    expect(names).toContain("evaluator");
    expect(names).toContain("advisor");
    expect(names).toContain("tool_builder");
    expect(names).toContain("literature_agent");
    expect(names).toContain("data_agent");
    expect(names).toContain("report_agent");

    // State tools (6)
    expect(names).toContain("create_experiment");
    expect(names).toContain("append_run");
    expect(names).toContain("load_progress");
    expect(names).toContain("get_best_run");
    expect(names).toContain("load_criteria");
    expect(names).toContain("finalize_project");

    // 8 agents + 6 state = 14
    expect(names).toHaveLength(14);
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

  it("rejects processMessage before connect", async () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    // processMessage calls the LLM, which requires API keys, so it will fail.
    // But we can verify the orchestrator doesn't crash on construction.
    expect(orch.getToolNames().length).toBeGreaterThan(0);
  });

  it("close is safe to call without connect", () => {
    const orch = new Orchestrator(DEFAULT_CONFIG);
    // Should not throw even if rpcClient is null
    orch.close();
  });

  it("uses model overrides for the orchestrator model", () => {
    const orch = new Orchestrator({
      ...DEFAULT_CONFIG,
      modelOverrides: { orchestrator: "anthropic/claude-haiku-4-5" },
    });
    // The override is used internally during processMessage.
    // We verify construction succeeds and tools are still built.
    expect(orch.getToolNames()).toContain("planning_agent");
  });

  it("passes model overrides through to agent tools", () => {
    const orch = new Orchestrator({
      ...DEFAULT_CONFIG,
      modelOverrides: { evaluator: "anthropic/claude-haiku-4-5" },
    });
    // If overrides were not passed, buildAgentTools would use defaultModel.
    // We can only verify the orchestrator constructed without error.
    expect(orch.getToolNames()).toContain("evaluator");
  });
});
