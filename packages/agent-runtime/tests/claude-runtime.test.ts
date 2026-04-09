import { describe, expect, it } from "bun:test";
import { ClaudeRuntime } from "../src/runtime/claude-runtime";

describe("ClaudeRuntime", () => {
  it("implements AgentRuntime interface", () => {
    const runtime = new ClaudeRuntime();
    expect(runtime.name).toBe("claude");
    expect(typeof runtime.authenticate).toBe("function");
    expect(typeof runtime.createAgent).toBe("function");
    expect(typeof runtime.listModels).toBe("function");
    expect(typeof runtime.getDefaultModel).toBe("function");
    expect(typeof runtime.isAuthenticated).toBe("function");
    expect(typeof runtime.getAuthStatus).toBe("function");
  });

  it("detects claude CLI availability", () => {
    const runtime = new ClaudeRuntime();
    // claude is installed at /home/mrichardson/.local/bin/claude
    const auth = runtime.isAuthenticated();
    expect(typeof auth).toBe("boolean");
  });

  it("returns false for nonexistent CLI path", () => {
    const runtime = new ClaudeRuntime({
      claudePath: "/nonexistent/claude",
    });
    expect(runtime.isAuthenticated()).toBe(false);
  });

  it("creates a ManagedAgent", () => {
    const runtime = new ClaudeRuntime();
    const agent = runtime.createAgent({
      name: "test",
      systemPrompt: "You are a test.",
      tools: [],
    });
    expect(agent).toBeDefined();
    expect(typeof agent.prompt).toBe("function");
    expect(typeof agent.subscribe).toBe("function");
    expect(typeof agent.steer).toBe("function");
    expect(typeof agent.abort).toBe("function");
    expect(agent.isRunning).toBe(false);
  });

  it("lists available models", () => {
    const runtime = new ClaudeRuntime();
    const models = runtime.listModels();
    expect(models.length).toBeGreaterThan(0);
    const ids = models.map((m) => m.id);
    expect(ids).toContain("claude-sonnet-4-6");
    expect(ids).toContain("claude-opus-4-6");
    expect(ids).toContain("claude-haiku-4-5");
    // Every model has required fields
    for (const model of models) {
      expect(model.provider).toBe("anthropic");
      expect(model.name.length).toBeGreaterThan(0);
    }
  });

  it("getDefaultModel returns sonnet", () => {
    const runtime = new ClaudeRuntime();
    expect(runtime.getDefaultModel()).toBe("sonnet");
  });

  it("getAuthStatus returns cli method", () => {
    const runtime = new ClaudeRuntime();
    const status = runtime.getAuthStatus();
    expect(status.method).toBe("cli");
    expect(status.provider).toBe("anthropic");
    expect(typeof status.active).toBe("boolean");
  });

  it("subscribe returns an unsubscribe function", () => {
    const runtime = new ClaudeRuntime();
    const agent = runtime.createAgent({
      name: "test",
      systemPrompt: "Test",
      tools: [],
    });
    const events: any[] = [];
    const unsub = agent.subscribe((e) => events.push(e));
    expect(typeof unsub).toBe("function");
    // Unsubscribe should not throw
    unsub();
  });

  it("abort on idle agent does not throw", () => {
    const runtime = new ClaudeRuntime();
    const agent = runtime.createAgent({
      name: "test",
      systemPrompt: "Test",
      tools: [],
    });
    // Should not throw when no process is running
    expect(() => agent.abort()).not.toThrow();
    expect(agent.isRunning).toBe(false);
  });

  it("steer on idle agent does not throw", () => {
    const runtime = new ClaudeRuntime();
    const agent = runtime.createAgent({
      name: "test",
      systemPrompt: "Test",
      tools: [],
    });
    // Should not throw when no process is running
    expect(() => agent.steer("hello")).not.toThrow();
  });

  it("accepts custom claudePath", () => {
    const runtime = new ClaudeRuntime({
      claudePath: "/home/mrichardson/.local/bin/claude",
    });
    expect(runtime.name).toBe("claude");
    // Should still work with explicit path
    const auth = runtime.isAuthenticated();
    expect(typeof auth).toBe("boolean");
  });
});
