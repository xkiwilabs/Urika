import { describe, expect, it } from "bun:test";
import { loadSystemConfig } from "../src/config/loader";
import { mkdtempSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

const SAMPLE_CONFIG = `
[system]
name = "test-system"
version = "1.0.0"
description = "A test system"
rpc_command = "python -m test.rpc"
prompts_dir = "prompts"

[runtime]
default_backend = "claude"
default_model = "anthropic/claude-sonnet-4-6"

[runtime.models]
evaluator = "anthropic/claude-haiku-4-5"
data_agent = "ollama/qwen3:14b"

[privacy]
mode = "hybrid"
local_agents = ["data_agent"]

[[agents]]
name = "planning_agent"
prompt = "planning_agent_system.md"
description = "Plans things"
tools = ["Read", "Glob"]

[[agents]]
name = "data_agent"
prompt = "data_agent_system.md"
description = "Handles data"
privacy = "local"

[[tools]]
name = "list_projects"
rpc_method = "project.list"
description = "List projects"
scope = "global"

[[tools]]
name = "create_experiment"
rpc_method = "experiment.create"
description = "Create experiment"
scope = "project"

[tools.params]
name = { type = "string", description = "Experiment name" }

[[commands]]
name = "project"
description = "Open a project"
scope = "global"
autocomplete_rpc = "project.list"

[[commands]]
name = "status"
description = "Show status"
scope = "project"

[orchestrator]
prompt = "orchestrator_system.md"
model_override = "anthropic/claude-opus-4-6"
`;

function writeConfig(content: string = SAMPLE_CONFIG): string {
  const dir = mkdtempSync(join(tmpdir(), "rt-test-"));
  const path = join(dir, "runtime.toml");
  writeFileSync(path, content);
  return path;
}

describe("loadSystemConfig", () => {
  it("parses system section", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.system.name).toBe("test-system");
    expect(config.system.version).toBe("1.0.0");
    expect(config.system.description).toBe("A test system");
    expect(config.system.rpcCommand).toBe("python -m test.rpc");
    expect(config.system.promptsDir).toBe("prompts");
  });

  it("parses runtime section with model overrides", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.runtime.defaultBackend).toBe("claude");
    expect(config.runtime.defaultModel).toBe("anthropic/claude-sonnet-4-6");
    expect(config.runtime.models.evaluator).toBe("anthropic/claude-haiku-4-5");
    expect(config.runtime.models.data_agent).toBe("ollama/qwen3:14b");
  });

  it("parses agents array", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.agents).toHaveLength(2);
    expect(config.agents[0].name).toBe("planning_agent");
    expect(config.agents[0].prompt).toBe("planning_agent_system.md");
    expect(config.agents[0].tools).toEqual(["Read", "Glob"]);
    expect(config.agents[0].privacy).toBeUndefined();
    expect(config.agents[1].name).toBe("data_agent");
    expect(config.agents[1].privacy).toBe("local");
    expect(config.agents[1].tools).toBeUndefined();
  });

  it("parses tools with params", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.tools).toHaveLength(2);
    expect(config.tools[0].name).toBe("list_projects");
    expect(config.tools[0].rpcMethod).toBe("project.list");
    expect(config.tools[0].scope).toBe("global");
    expect(config.tools[0].params).toBeUndefined();
    expect(config.tools[1].name).toBe("create_experiment");
    expect(config.tools[1].scope).toBe("project");
    expect(config.tools[1].params).toBeDefined();
    expect(config.tools[1].params!.name.type).toBe("string");
    expect(config.tools[1].params!.name.description).toBe("Experiment name");
  });

  it("parses commands with autocomplete", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.commands).toHaveLength(2);
    expect(config.commands[0].name).toBe("project");
    expect(config.commands[0].scope).toBe("global");
    expect(config.commands[0].autocompleteRpc).toBe("project.list");
    expect(config.commands[1].name).toBe("status");
    expect(config.commands[1].scope).toBe("project");
    expect(config.commands[1].autocompleteRpc).toBeUndefined();
  });

  it("parses privacy section", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.privacy.mode).toBe("hybrid");
    expect(config.privacy.localAgents).toEqual(["data_agent"]);
  });

  it("parses orchestrator section", () => {
    const config = loadSystemConfig(writeConfig());
    expect(config.orchestrator.prompt).toBe("orchestrator_system.md");
    expect(config.orchestrator.modelOverride).toBe(
      "anthropic/claude-opus-4-6",
    );
  });

  it("applies defaults for missing sections", () => {
    const config = loadSystemConfig(
      writeConfig(`
[system]
name = "minimal"
`),
    );
    expect(config.system.name).toBe("minimal");
    expect(config.system.version).toBe("0.0.0");
    expect(config.runtime.defaultBackend).toBe("pi");
    expect(config.runtime.defaultModel).toBe("anthropic/claude-sonnet-4-6");
    expect(config.runtime.models).toEqual({});
    expect(config.privacy.mode).toBe("open");
    expect(config.privacy.localAgents).toEqual([]);
    expect(config.agents).toEqual([]);
    expect(config.tools).toEqual([]);
    expect(config.commands).toEqual([]);
    expect(config.orchestrator.prompt).toBe("orchestrator_system.md");
    expect(config.orchestrator.modelOverride).toBeUndefined();
  });
});
