import { describe, expect, it } from "bun:test";
import { loadUrikaConfig } from "../src/config/loader";
import { mkdtempSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

describe("loadUrikaConfig", () => {
  it("loads model config from urika.toml", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-test-"));
    writeFileSync(join(dir, "urika.toml"), `
[project]
name = "test"
question = "Does X?"
mode = "exploratory"

[runtime]
default_model = "anthropic/claude-sonnet-4-6"

[runtime.models]
evaluator = "anthropic/claude-haiku-4-5"
data_agent = "ollama/qwen3:14b"
`);
    const config = loadUrikaConfig(dir);
    expect(config.defaultModel).toBe("anthropic/claude-sonnet-4-6");
    expect(config.models.evaluator).toBe("anthropic/claude-haiku-4-5");
    expect(config.models.data_agent).toBe("ollama/qwen3:14b");
  });

  it("returns defaults when runtime section missing", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-test-"));
    writeFileSync(join(dir, "urika.toml"), `
[project]
name = "test"
question = "Does X?"
mode = "exploratory"
`);
    const config = loadUrikaConfig(dir);
    expect(config.defaultModel).toBe("anthropic/claude-sonnet-4-6");
    expect(Object.keys(config.models)).toHaveLength(0);
  });

  it("loads privacy config", () => {
    const dir = mkdtempSync(join(tmpdir(), "urika-test-"));
    writeFileSync(join(dir, "urika.toml"), `
[project]
name = "test"
question = "X?"
mode = "exploratory"

[privacy]
mode = "hybrid"
local_roles = ["data_agent"]
`);
    const config = loadUrikaConfig(dir);
    expect(config.privacyMode).toBe("hybrid");
    expect(config.localRoles).toContain("data_agent");
  });
});
