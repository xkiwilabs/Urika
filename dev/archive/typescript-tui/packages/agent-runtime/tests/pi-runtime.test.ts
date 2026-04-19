import { describe, expect, it } from "bun:test";
import { PiRuntime } from "../src/runtime/pi-runtime";
import type { ManagedAgent, RuntimeEvent, AgentConfig } from "../src/runtime/types";

describe("PiRuntime", () => {
  it("implements AgentRuntime interface", () => {
    const runtime = new PiRuntime();
    expect(runtime.name).toBe("pi");
    expect(typeof runtime.authenticate).toBe("function");
    expect(typeof runtime.isAuthenticated).toBe("function");
    expect(typeof runtime.getAuthStatus).toBe("function");
    expect(typeof runtime.createAgent).toBe("function");
    expect(typeof runtime.listModels).toBe("function");
    expect(typeof runtime.getDefaultModel).toBe("function");
  });

  it("returns default model", () => {
    const runtime = new PiRuntime();
    expect(runtime.getDefaultModel()).toBe("anthropic/claude-sonnet-4-6");
  });

  it("returns auth status with api-key method", () => {
    const runtime = new PiRuntime();
    const status = runtime.getAuthStatus();
    expect(status.provider).toBe("pi-multi");
    expect(status.method).toBe("api-key");
    expect(typeof status.active).toBe("boolean");
  });

  it("authenticate resolves without error", async () => {
    const runtime = new PiRuntime();
    await expect(runtime.authenticate()).resolves.toBeUndefined();
  });

  it("lists available models from pi-ai", () => {
    const runtime = new PiRuntime();
    const models = runtime.listModels();
    expect(Array.isArray(models)).toBe(true);
    // pi-ai has built-in model definitions
    expect(models.length).toBeGreaterThan(0);
    // Each model has the required fields
    for (const model of models) {
      expect(typeof model.id).toBe("string");
      expect(typeof model.provider).toBe("string");
      expect(typeof model.name).toBe("string");
    }
  });

  it("accepts an apiKey resolver in constructor", () => {
    const resolver = async (_provider: string) => "test-key";
    const runtime = new PiRuntime({ getApiKey: resolver });
    expect(runtime.name).toBe("pi");
  });

  describe("createAgent", () => {
    it("creates a ManagedAgent with required interface", () => {
      const runtime = new PiRuntime();
      const agent = runtime.createAgent({
        name: "test",
        systemPrompt: "You are a test agent.",
        tools: [],
      });
      expect(agent).toBeDefined();
      expect(typeof agent.prompt).toBe("function");
      expect(typeof agent.subscribe).toBe("function");
      expect(typeof agent.steer).toBe("function");
      expect(typeof agent.abort).toBe("function");
      expect(agent.isRunning).toBe(false);
    });

    it("creates agent with tools", () => {
      const runtime = new PiRuntime();
      const agent = runtime.createAgent({
        name: "test-with-tools",
        systemPrompt: "You are a test agent.",
        tools: [
          {
            name: "list_items",
            description: "List all items",
            scope: "global",
            params: {
              query: { type: "string", description: "Search query", optional: true },
            },
          },
        ],
        toolExecutors: {
          list_items: async (args: any) => ({ items: ["a", "b", "c"] }),
        },
      });
      expect(agent).toBeDefined();
      expect(agent.isRunning).toBe(false);
    });

    it("creates agent with custom model", () => {
      const runtime = new PiRuntime();
      // This should not throw — openai/gpt-4o is a known model in pi-ai
      const agent = runtime.createAgent({
        name: "test-model",
        systemPrompt: "You are a test agent.",
        tools: [],
        model: "openai/gpt-4o",
      });
      expect(agent).toBeDefined();
    });

    it("handles unknown model gracefully (pi-ai returns stub)", () => {
      const runtime = new PiRuntime();
      // pi-ai's getModel returns a stub for unknown models rather than throwing
      const agent = runtime.createAgent({
        name: "unknown-model",
        systemPrompt: "test",
        tools: [],
        model: "nonexistent/fake-model-xyz",
      });
      expect(agent).toBeDefined();
      expect(agent.isRunning).toBe(false);
    });
  });

  describe("ManagedAgent subscribe/unsubscribe", () => {
    it("returns an unsubscribe function", () => {
      const runtime = new PiRuntime();
      const agent = runtime.createAgent({
        name: "sub-test",
        systemPrompt: "test",
        tools: [],
      });
      const events: RuntimeEvent[] = [];
      const unsub = agent.subscribe((event) => events.push(event));
      expect(typeof unsub).toBe("function");
      // Unsubscribe should not throw
      unsub();
    });
  });

  describe("ManagedAgent abort", () => {
    it("does not throw when called without an active run", () => {
      const runtime = new PiRuntime();
      const agent = runtime.createAgent({
        name: "abort-test",
        systemPrompt: "test",
        tools: [],
      });
      expect(() => agent.abort()).not.toThrow();
    });
  });

  describe("ManagedAgent steer", () => {
    it("does not throw when called without an active run", () => {
      const runtime = new PiRuntime();
      const agent = runtime.createAgent({
        name: "steer-test",
        systemPrompt: "test",
        tools: [],
      });
      expect(() => agent.steer("redirect to topic X")).not.toThrow();
    });
  });
});
