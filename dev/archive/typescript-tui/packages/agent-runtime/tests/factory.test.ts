import { describe, expect, it } from "bun:test";
import { createRuntime } from "../src/runtime/factory";
import { PiRuntime } from "../src/runtime/pi-runtime";
import { ClaudeRuntime } from "../src/runtime/claude-runtime";
import { CodexRuntime } from "../src/runtime/codex-runtime";
import { GoogleRuntime } from "../src/runtime/google-runtime";

describe("createRuntime factory", () => {
  it("creates PiRuntime for 'pi'", () => {
    const runtime = createRuntime("pi");
    expect(runtime).toBeInstanceOf(PiRuntime);
    expect(runtime.name).toBe("pi");
  });

  it("creates ClaudeRuntime for 'claude'", () => {
    const runtime = createRuntime("claude");
    expect(runtime).toBeInstanceOf(ClaudeRuntime);
    expect(runtime.name).toBe("claude");
  });

  it("creates CodexRuntime for 'codex'", () => {
    const runtime = createRuntime("codex");
    expect(runtime).toBeInstanceOf(CodexRuntime);
    expect(runtime.name).toBe("codex");
  });

  it("creates GoogleRuntime for 'google'", () => {
    const runtime = createRuntime("google");
    expect(runtime).toBeInstanceOf(GoogleRuntime);
    expect(runtime.name).toBe("google");
  });

  it("passes claudePath option to ClaudeRuntime", () => {
    const runtime = createRuntime("claude", { claudePath: "/usr/bin/claude" });
    expect(runtime).toBeInstanceOf(ClaudeRuntime);
  });

  it("passes getApiKey option to PiRuntime", () => {
    const getApiKey = async () => "test-key";
    const runtime = createRuntime("pi", { getApiKey });
    expect(runtime).toBeInstanceOf(PiRuntime);
  });

  it("throws for unknown backend", () => {
    expect(() => createRuntime("unknown")).toThrow(
      "Unknown runtime backend: unknown. Available: claude, pi, codex, google",
    );
  });

  it("throws with descriptive message for empty string", () => {
    expect(() => createRuntime("")).toThrow("Unknown runtime backend:");
  });
});
