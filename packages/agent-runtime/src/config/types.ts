export interface SystemConfig {
  system: {
    name: string;
    version: string;
    description: string;
    rpcCommand: string;
    promptsDir: string;
  };
  runtime: {
    defaultBackend: string;
    defaultModel: string;
    models: Record<string, string>; // per-agent model overrides
  };
  privacy: {
    mode: "open" | "hybrid" | "private";
    localAgents: string[];
  };
  agents: AgentDeclaration[];
  tools: ToolDeclaration[];
  commands: CommandDeclaration[];
  orchestrator: {
    prompt: string;
    modelOverride?: string;
  };
}

export interface AgentDeclaration {
  name: string;
  prompt: string;
  description: string;
  tools?: string[];
  privacy?: "local" | "cloud";
  model?: string;
}

export interface ToolDeclaration {
  name: string;
  rpcMethod: string;
  description: string;
  scope: "global" | "project";
  special?: string;
  params?: Record<
    string,
    { type: string; description?: string; optional?: boolean }
  >;
}

export interface CommandDeclaration {
  name: string;
  description: string;
  scope: "global" | "project";
  autocompleteRpc?: string;
}
