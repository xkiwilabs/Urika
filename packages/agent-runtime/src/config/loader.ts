import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { parse as parseTOML } from "smol-toml";
import type { SystemConfig } from "./types";

/**
 * Load and parse a runtime.toml file into a structured SystemConfig.
 *
 * TOML snake_case keys are mapped to camelCase TypeScript properties.
 * Missing sections or keys fall back to sensible defaults.
 */
export function loadSystemConfig(configPath: string): SystemConfig {
  const raw = readFileSync(configPath, "utf-8");
  const parsed = parseTOML(raw) as Record<string, any>;
  const configDir = dirname(resolve(configPath));

  return {
    system: {
      name: parsed.system?.name ?? "",
      version: parsed.system?.version ?? "0.0.0",
      description: parsed.system?.description ?? "",
      rpcCommand: parsed.system?.rpc_command ?? "",
      promptsDir: parsed.system?.prompts_dir
        ? resolve(configDir, parsed.system.prompts_dir)
        : "",
    },
    runtime: {
      defaultBackend: parsed.runtime?.default_backend ?? "pi",
      defaultModel:
        parsed.runtime?.default_model ?? "anthropic/claude-sonnet-4-6",
      models: parsed.runtime?.models ?? {},
    },
    privacy: {
      mode: parsed.privacy?.mode ?? "open",
      localAgents: parsed.privacy?.local_agents ?? [],
    },
    agents: (parsed.agents ?? []).map((a: any) => ({
      name: a.name,
      prompt: a.prompt ?? "",
      description: a.description ?? "",
      tools: a.tools,
      privacy: a.privacy,
      model: a.model,
    })),
    tools: (parsed.tools ?? []).map((t: any) => ({
      name: t.name,
      rpcMethod: t.rpc_method ?? "",
      description: t.description ?? "",
      scope: t.scope ?? "project",
      special: t.special,
      params: t.params,
    })),
    commands: (parsed.commands ?? []).map((c: any) => ({
      name: c.name,
      description: c.description ?? "",
      scope: c.scope ?? "global",
      autocompleteRpc: c.autocomplete_rpc,
    })),
    orchestrator: {
      prompt: parsed.orchestrator?.prompt ?? "orchestrator_system.md",
      modelOverride: parsed.orchestrator?.model_override,
    },
  };
}
