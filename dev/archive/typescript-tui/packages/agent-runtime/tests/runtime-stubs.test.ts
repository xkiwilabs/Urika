import { describe, expect, it } from "bun:test";
import { CodexRuntime } from "../src/runtime/codex-runtime";
import { GoogleRuntime } from "../src/runtime/google-runtime";

describe("CodexRuntime (stub)", () => {
  const runtime = new CodexRuntime();

  it("has name 'codex'", () => {
    expect(runtime.name).toBe("codex");
  });

  it("isAuthenticated returns false", () => {
    expect(runtime.isAuthenticated()).toBe(false);
  });

  it("getAuthStatus returns inactive", () => {
    const status = runtime.getAuthStatus();
    expect(status.provider).toBe("openai");
    expect(status.method).toBe("api-key");
    expect(status.active).toBe(false);
  });

  it("authenticate throws not implemented", async () => {
    await expect(runtime.authenticate()).rejects.toThrow("not yet implemented");
  });

  it("createAgent throws not implemented", () => {
    expect(() =>
      runtime.createAgent({
        name: "test",
        systemPrompt: "",
        tools: [],
      }),
    ).toThrow("not yet implemented");
  });

  it("listModels returns empty array", () => {
    expect(runtime.listModels()).toEqual([]);
  });

  it("getDefaultModel returns openai model", () => {
    expect(runtime.getDefaultModel()).toBe("openai/gpt-4o");
  });
});

describe("GoogleRuntime (stub)", () => {
  const runtime = new GoogleRuntime();

  it("has name 'google'", () => {
    expect(runtime.name).toBe("google");
  });

  it("isAuthenticated returns false", () => {
    expect(runtime.isAuthenticated()).toBe(false);
  });

  it("getAuthStatus returns inactive", () => {
    const status = runtime.getAuthStatus();
    expect(status.provider).toBe("google");
    expect(status.method).toBe("api-key");
    expect(status.active).toBe(false);
  });

  it("authenticate throws not implemented", async () => {
    await expect(runtime.authenticate()).rejects.toThrow("not yet implemented");
  });

  it("createAgent throws not implemented", () => {
    expect(() =>
      runtime.createAgent({
        name: "test",
        systemPrompt: "",
        tools: [],
      }),
    ).toThrow("not yet implemented");
  });

  it("listModels returns empty array", () => {
    expect(runtime.listModels()).toEqual([]);
  });

  it("getDefaultModel returns google model", () => {
    expect(runtime.getDefaultModel()).toBe("google/gemini-2.5-pro");
  });
});
