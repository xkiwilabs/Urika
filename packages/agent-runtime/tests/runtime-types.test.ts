import { describe, expect, it } from "bun:test";
import type {
  AgentRuntime,
  ManagedAgent,
  RuntimeEvent,
  UsageStats,
  AgentConfig,
  ToolDefinition,
  AgentDeclaration,
  CommandDeclaration,
  RuntimeBackend,
  AuthStatus,
  ModelInfo,
} from "../src/runtime/types";

describe("Runtime types", () => {
  it("RuntimeBackend accepts valid values", () => {
    const backends: RuntimeBackend[] = ["claude", "pi", "codex", "google"];
    expect(backends).toHaveLength(4);
  });

  it("RuntimeEvent type covers all event types", () => {
    const events: RuntimeEvent[] = [
      { type: "text_delta", delta: "hello" },
      { type: "thinking_delta", delta: "hmm" },
      { type: "tool_start", name: "test", args: {} },
      { type: "tool_end", name: "test", result: {}, isError: false },
      { type: "agent_start" },
      {
        type: "agent_end",
        usage: {
          tokensIn: 0,
          tokensOut: 0,
          cost: 0,
          model: "test",
          elapsed: 0,
        },
      },
      { type: "error", message: "oops" },
    ];
    expect(events).toHaveLength(7);
  });

  it("ToolDefinition supports RPC and special tools", () => {
    const tool: ToolDefinition = {
      name: "list_projects",
      description: "List all projects",
      scope: "global",
      rpcMethod: "project.list",
    };
    expect(tool.scope).toBe("global");

    const special: ToolDefinition = {
      name: "switch_project",
      description: "Switch project",
      scope: "global",
      special: "switch_project",
    };
    expect(special.special).toBe("switch_project");
  });
});
