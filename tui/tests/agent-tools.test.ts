import { describe, expect, it } from "bun:test";
import { buildAgentTools, AGENT_ROLES } from "../src/orchestrator/agent-tools";

describe("AGENT_ROLES", () => {
  it("maps role names to prompt filenames", () => {
    expect(AGENT_ROLES.planning_agent).toBe("planning_agent_system.md");
    expect(AGENT_ROLES.task_agent).toBe("task_agent_system.md");
    expect(AGENT_ROLES.evaluator).toBe("evaluator_system.md");
    expect(AGENT_ROLES.advisor).toBe("advisor_agent_system.md");
  });

  it("has 8 agent roles", () => {
    expect(Object.keys(AGENT_ROLES)).toHaveLength(8);
  });
});

describe("buildAgentTools", () => {
  it("creates a tool for each agent role", () => {
    const tools = buildAgentTools({
      promptsDir: "/nonexistent",  // will use fallback prompts
      projectDir: "/tmp/test",
      experimentId: "exp-001",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
    });
    expect(tools).toHaveLength(8);
    const names = tools.map((t) => t.name);
    expect(names).toContain("planning_agent");
    expect(names).toContain("task_agent");
    expect(names).toContain("evaluator");
    expect(names).toContain("advisor");
    expect(names).toContain("tool_builder");
    expect(names).toContain("literature_agent");
    expect(names).toContain("data_agent");
    expect(names).toContain("report_agent");
  });

  it("each tool has name, description, model, systemPrompt, and execute", () => {
    const tools = buildAgentTools({
      promptsDir: "/nonexistent",
      projectDir: "/tmp/test",
      experimentId: "exp-001",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
    });
    for (const tool of tools) {
      expect(typeof tool.name).toBe("string");
      expect(typeof tool.description).toBe("string");
      expect(typeof tool.model).toBe("string");
      expect(typeof tool.systemPrompt).toBe("string");
      expect(typeof tool.execute).toBe("function");
    }
  });

  it("applies model overrides per role", () => {
    const tools = buildAgentTools({
      promptsDir: "/nonexistent",
      projectDir: "/tmp/test",
      experimentId: "exp-001",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {
        evaluator: "anthropic/claude-haiku-4-5",
        data_agent: "ollama/qwen3:14b",
      },
    });
    const evaluator = tools.find((t) => t.name === "evaluator")!;
    const dataAgent = tools.find((t) => t.name === "data_agent")!;
    const planner = tools.find((t) => t.name === "planning_agent")!;
    expect(evaluator.model).toBe("anthropic/claude-haiku-4-5");
    expect(dataAgent.model).toBe("ollama/qwen3:14b");
    expect(planner.model).toBe("anthropic/claude-sonnet-4-6");  // default
  });

  it("uses fallback prompt when file not found", () => {
    const tools = buildAgentTools({
      promptsDir: "/nonexistent",
      projectDir: "/tmp/test",
      experimentId: "exp-001",
      defaultModel: "anthropic/claude-sonnet-4-6",
      modelOverrides: {},
    });
    const planner = tools.find((t) => t.name === "planning_agent")!;
    expect(planner.systemPrompt).toBe("You are the planning_agent.");
  });
});
